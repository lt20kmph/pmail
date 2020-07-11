#!/usr/bin/python

# ---> Imports

import pickle
import os.path
import os
import sys
import socket
import logging
import argparse

from apiclient import errors
from common import (mkService, Session, Labels, MessageInfo,
                    listMessagesMatchingQuery, logger,
                    UserInfo, AddressBook, config)
from googleapiclient.http import BatchHttpRequest
from threading import Thread, Lock
from time import sleep

# <---


# ---> DB update and synchronisation


# ---> Pickling

def storeLastHistoryId(account, session, lastMessageId=None, lastHistoryId=None):
  '''
  Pickle the last historyId for use when updating the db.

  Args:
    account: Account whose history we are pickling.
    lastMessageId = The id of the last message saved in the db.
    lastHistoryId = The lastHistoryId.

  Returns:
    None
  '''
  path = os.path.join(config.pickleDir, 'lastHistoryId.' + account + '.pickle')
  if lastMessageId:
    q = session.query(MessageInfo).get(lastMessageId)
    with open(path, 'wb') as f:
      pickle.dump(q.historyId, f)
  elif lastHistoryId:
    with open(path, 'wb') as f:
      pickle.dump(lastHistoryId, f)


def getLastHistoryId(account):
  '''
  Get the last history for account from the pickle if it exists.
  '''
  path = os.path.join(config.pickleDir, 'lastHistoryId.' + account + '.pickle')
  if os.path.exists(path):
    with open(path, 'rb') as f:
      return pickle.load(f)

# <---

# ---> List changes since last update


def ListHistory(service, user_id, start_history_id='1'):
  """
  List History of all changes to the user's mailbox.

 Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    start_history_id: Only return Histories at or after start_history_id.

  Returns:
    A list of mailbox changes that occurred after the start_history_id.
  """
  try:
    history = (service.users().history().list(userId=user_id,
                                              startHistoryId=start_history_id)
               .execute())
    changes = history['history'] if 'history' in history else []
    while 'nextPageToken' in history:
      page_token = history['nextPageToken']
      history = (service.users().history().list(userId=user_id,
                                                startHistoryId=start_history_id,
                                                pageToken=page_token).execute())
      changes.extend(history['history'])

    return changes
  except errors.Error as e:
    logger.debug(e)

# <---


def updateDb(account, session, service, lastHistoryId=None):
  '''
  Update the Database with messages since lastHistoryId.

  Args: 
    account: The account which the messages come from.
    session: DB session.
    service: The google API sevice object.
    lastHistoryId: The historyId of the last update, if there was one.

  Returns:
    None.
  '''
  # 100 is maximum size of batch!
  if lastHistoryId is None:
    messageIds = listMessagesMatchingQuery(service(account),
                                           'me', query='newer_than:' + config.syncFrom)
    MessageInfo.addMessages(session, account,
                            service(account), [m['id'] for m in messageIds])
    lastMessageId = messageIds[0]['id']
  else:
    changes = ListHistory(service(account), 'me', getLastHistoryId(account))
    messagesAdded, messagesDeleted = [], []
    labelsAdded, labelsRemoved = [], []
    for change in changes:
      if 'messagesAdded' in change:
        messagesAdded += [c['message']['id'] for c in
                          change['messagesAdded']]
      if 'messagesDeleted' in change:
        messagesDeleted += [c['message']['id'] for c in
                            change['messagesDeleted']]
      if 'labelsAdded' in change:
        labelsAdded += [(c['message']['id'], c['labelIds']) for c in
                        change['labelsAdded']]
      if 'labelsRemoved' in change:
        labelsRemoved += [(c['message']['id'], c['labelIds']) for c in
                          change['labelsRemoved']]
    MessageInfo.addMessages(session, account, service(account), messagesAdded)
    MessageInfo.removeMessages(session, messagesDeleted)
    Labels.addLabels(session, labelsAdded)
    Labels.removeLabels(session, labelsRemoved)
    try:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
    except:
      lastHistoryId = None
    lastMessageId = None
  storeLastHistoryId(account, session, lastMessageId=lastMessageId,
                     lastHistoryId=lastHistoryId)

# <---

# ---> Server Functions


def getMessages(s, account, query, position, height, excludedLabels=[],
                includedLabels=[], count=False):
  '''
  Get a list of messages to display.

  Args:
    account: The currently selected account.
    query: list of messageIds.
    position: The position of the currently highlighted message.
    height: The height of the stdscr.
    excludedLabels: Any labels to exclude,
    includedLabels: Any labels to include.
    count: if True then only return the count.

  Returns:
    Either a list of MessageInfo objects or
    an integer (depending on truthiness of count).
  '''
  excludeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(excludedLabels))
  includeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(includedLabels))
  q = s.query(MessageInfo)\
      .filter(
          MessageInfo.messageId.in_(query),
          MessageInfo.emailAddress == account,
          ~MessageInfo.messageId.in_(excludeQuery),
          MessageInfo.messageId.in_(includeQuery))\
      .order_by(MessageInfo.time.desc())
  if count == False:
    return [h for h in q.slice(position, position+height-2)]
  elif count == True:
    return q.count()
# <---

# ---> Main


def pmailServer(lock):
    # get the hostname
  host = socket.gethostname()
  port = config.port
  bufferSize = 1024

  sock = socket.socket()
  sock.bind((host, port))
  s = Session()

  # configure how many client the server can listen simultaneously
  # only accept connections from runClient?
  sock.listen(1)
  while 1:
    conn, address = sock.accept()
    print("Connection from: " + str(address))
    sizeOfIncoming = int.from_bytes(conn.recv(4), 'big')
    print(sizeOfIncoming)
    incoming = b''

    while len(incoming) < sizeOfIncoming:
      incoming += conn.recv(bufferSize)

    unpickledIncoming = pickle.loads(incoming, encoding='bytes')

    # Do something and return a response.
    action = unpickledIncoming['action']
    with lock:
      if action == 'GET_MESSAGES':
        # Get messages.
        incomingQ = unpickledIncoming['query']
        query = s.query(MessageInfo.messageId) if incomingQ is None else incomingQ
        response = getMessages(s,
                               unpickledIncoming['account'],
                               query,
                               unpickledIncoming['position'],
                               unpickledIncoming['height'],
                               unpickledIncoming['excludedLabels'],
                               unpickledIncoming['includedLabels'],
                               unpickledIncoming['count'])
      elif action == 'ADD_MESSAGES':
        # Add messages.
        account = unpickledIncoming['account']
        messageIds = unpickledIncoming['messageIds']
        MessageInfo.addMessages(s, account, mkService(account), messageIds)
        response = None
      elif action == 'GET_QUERY':
        # get a query.
        messageIds = unpickledIncoming['messageIds']
        cls = unpickledIncoming['class']
        response = [e for e in s.query(cls)\
                    .filter(cls.messageId.in_(messageIds))]
      elif action == 'REMOVE_LABELS':
        # Remove labels.
        logger.info('Recieved instructions from client'
                    + '{}'.format(unpickledIncoming))
        labels = unpickledIncoming['labels']
        Labels.removeLabels(s, labels)
        response = None
      elif action == 'ADD_LABELS':
        # Add labels.
        logger.info('Recieved instructions from client'
                    + '{}'.format(unpickledIncoming))
        labels = unpickledIncoming['labels']
        Labels.addLabels(s, labels)
        response = None
      elif action == 'REMOVE_FALSE_ATTACMENTS':
        # Remove false attachments.
        messageId = unpickledIncoming['messageId']
        s.query(MessageInfo).filter(MessageInfo.messageId == messageId)\
            .update({MessageInfo.hasAttachments: False},
                    synchronize_session='evaluate')

    pickledResponse = pickle.dumps(response)
    sizeOfPickle = len(pickledResponse)
    numOfChunks = sizeOfPickle//bufferSize + 1
    conn.send(sizeOfPickle.to_bytes(4, 'big'))

    for i in range(numOfChunks):
      conn.send(pickledResponse[i*bufferSize: (i+1)*bufferSize])

    if action == 'REMOVE_LABELS':
      for account in config.listAccounts():
        UserInfo.update(s,account,None)
    s.commit()
    s.close()
    print('closing connection..')
    conn.close()


def syncDb(lock):
  s = Session()
  while 1:
    try:
      with open(os.path.join(config.pickleDir, 'synced.pickle'), 'rb') as f:
        shouldIupdate = pickle.load(f)
    except:
      shouldIupdate = True
    try:
      with lock:
        logger.info('Aquiered lock, making session')
        # if os.path.exists(config.dbPath):
        if shouldIupdate == False:
          for account in config.listAccounts():
            logger.info('Performing partial update for {}'.format(account))
            updateDb(account, s, mkService, getLastHistoryId(account))
            UserInfo.update(s, account, None)
            logger.info('Successfully update {}'.format(account))
        else:
          for account in config.listAccounts():
            logger.info('Performing full update for {}'.format(account))
            updateDb(account, s, mkService)
            UserInfo.update(s, account, mkService(account))
            logger.info('Successfully update {}'.format(account))
            with open(os.path.join(config.pickleDir,
                                   'synced.pickle'), 'wb') as f:
              pickle.dump(False, f)
      s.close()
    except KeyboardInterrupt as k:
      print(k)
    sleep(config.updateFreq)

  print("Bye!")

  sys.exit()


if __name__ == '__main__':

  logger.setLevel(logging.DEBUG)
  logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

  parser = argparse.ArgumentParser()
  parser.add_argument('-n', action='store')
  args = parser.parse_args()

  if args.n == None:
    lock = Lock()
    t1 = Thread(target=pmailServer, args=(lock,), daemon=True)
    t2 = Thread(target=syncDb, args=(lock,))
    t1.start()
    t2.start()
  else:
    s = Session()
    q = s.query(UserInfo.numOfUnreadMessages)\
      .filter(UserInfo.emailAddress == args.n)
    print(q[0][0])
    Session.remove()

# <---

"""
vim:foldmethod=marker foldmarker=--->,<---
"""
