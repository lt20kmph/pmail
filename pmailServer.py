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
  # path = os.path.join(config.pickleDir, 'lastHistoryId.' + account + '.pickle')
  if lastMessageId:
    lastHistoryId = session.query(MessageInfo).get(lastMessageId).historyId
    q = session.query(UserInfo).get(account)
    q.historyId = lastHistoryId
    session.commit()
    # with open(path, 'wb') as f:
    #   pickle.dump(q.historyId, f)
  elif lastHistoryId:
    q = session.query(UserInfo).get(account)
    q.historyId = lastHistoryId
    session.commit()
    # with open(path, 'wb') as f:
    #   pickle.dump(lastHistoryId, f)


def getLastHistoryId(account,session):
  '''
  Get the last history for account from the pickle if it exists.
  '''
  # path = os.path.join(config.pickleDir, 'lastHistoryId.' + account + '.pickle')
  # if os.path.exists(path):
  #   with open(path, 'rb') as f:
  #     return pickle.load(f)
  return session.query(UserInfo).get(account).historyId


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
    changes = ListHistory(service(account), 'me',
                          getLastHistoryId(account,session))
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
  # storeLastHistoryId(account, session, lastMessageId=lastMessageId,
  #                    lastHistoryId=lastHistoryId)
  if lastMessageId:
    lastHistoryId = session.query(MessageInfo).get(lastMessageId).historyId
  return lastHistoryId

# <---

# ---> Server Functions


def getMessages(s, account, query, position, height, excludedLabels=[],
                includedLabels=[], count=False, afterAction=None):
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
  # excludeQuery = s.query(Labels.messageId).filter(
  #     Labels.label.in_(excludedLabels))
  # includeQuery = s.query(Labels.messageId).filter(
  #     Labels.label.in_(includedLabels))
  # q = s.query(MessageInfo)\
  #     .filter(
  #         MessageInfo.messageId.in_(query),
  #         MessageInfo.emailAddress == account,
  #         ~MessageInfo.messageId.in_(excludeQuery),
  #         MessageInfo.messageId.in_(includeQuery))\
  #     .order_by(MessageInfo.time.desc())
  if afterAction == None:
    q = Q.getQuery(s, account,query,includedLabels,excludedLabels)
  elif afterAction['action'] == 'DELETE':
    q = Q.removeMessages(afterAction['messageIds'])
  elif afterAction['action'] in ['MARK_AS_READ','YES']:
    # logger.info('removing msg from cache')
    q = Q.getQuery(s, account,query,includedLabels,excludedLabels, read=True)
    # q = Q.markAsRead(afterAction['messageIds'])
  if count == False:
    # return [h for h in q.slice(position, position + height - 2)]
    return q[position:position + height -2]
  elif count == True:
    # return q.count()
    return len(q)

class SaveQuery():

  def __init__(self):
    self.account = None
    self.query = None
    self.includedLabels = None
    self.excludedLabels = None
    self.savedQuery = None

  def getQuery(self,s,account,query,includedLabels,excludedLabels,read=False):
    # Also deletes, new mails, mark as read, etc..
    if (self.account == account and
        str(self.query) == str(query) and
        self.includedLabels == includedLabels and
        self.excludedLabels == excludedLabels) and read == False:
      logger.info('using saved query')
      return self.savedQuery
    else:
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
      self.account = account
      self.query = query
      self.includedLabels = includedLabels
      self.excludedLabels = excludedLabels
      self.savedQuery = list(q)
      logger.info('generating new query')
      return self.savedQuery

  def removeMessages(self, messageIds):
    self.savedQuery = [m for m in self.savedQuery if m.messageId not in
                       messageIds]
    return self.savedQuery

  def markAsRead(self, messageIds):
    newSavedQuery = []
    for m in self.savedQuery:
      if m.messageId in messageIds:
        m.read = True
        logger.info('setting read to True on msg: {}'.format(m.messageId))
      newSavedQuery.append(m)
    self.savedQuery = newSavedQuery
    return self.savedQuery

'''
def getNextMessage(s, account, query, lastTime, excludedLabels=[],
                includedLabels=[]):
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
      .filter(MessageInfo.time < lastTime)\
      .order_by(MessageInfo.time.desc())
  return q.first() 

'''

# <---

# ---> Main


def pmailServer(lock):
    # get the hostname
  host = socket.gethostname()
  port = config.port
  bufferSize = 1024

  portFree = True
  while portFree == True:
    try:
      sock = socket.socket()
      sock.bind((host, port))
      portFree = False
    except OSError as e:
      print(e)
      logger.info('checking port again in 30s')
      sleep(30)

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
        # logger.info('afterAction: {}'.format(unpickledIncoming['afterAction']))
        response = getMessages(s,
                               unpickledIncoming['account'],
                               query,
                               unpickledIncoming['position'],
                               unpickledIncoming['height'],
                               unpickledIncoming['excludedLabels'],
                               unpickledIncoming['includedLabels'],
                               unpickledIncoming['count'],
                               unpickledIncoming['afterAction'])
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
        UserInfo.update(s,account,None,None)
    s.commit()
    s.close()
    print('closing connection..')
    conn.close()


def syncDb(lock):
  s = Session()
  while 1:
    try:
      with lock:
        logger.info('Aquiered lock, making session')
        for account in config.listAccounts():
          shouldIupdate = s.query(UserInfo).get(account)
          if shouldIupdate and shouldIupdate.shouldIupdate == False:
            logger.info('Performing partial update for {}'.format(account))
            lastHistoryId = updateDb(account, s, mkService,
                     getLastHistoryId(account, s))
            UserInfo.update(s, account, None, lastHistoryId)
            logger.info('Successfully update {}'.format(account))
          elif shouldIupdate is None or shouldIupdate.shouldIupdate == True:
            logger.info('Performing full update for {}'.format(account))
            lastHistoryId = updateDb(account, s, mkService)
            UserInfo.update(s, account, mkService(account), lastHistoryId)
            logger.info('Successfully update {}'.format(account))
            with open(os.path.join(config.pickleDir,
                                   'synced.pickle'), 'wb') as f:
              pickle.dump(False, f)
      s.close()
    except Exception as e:
      logger.warning(e)
      logger.info('unable to update DB, trying again soon')
    except KeyboardInterrupt as k:
      print("Bye!")
      logger.info(k)
      sys.exit()
    sleep(config.updateFreq)



if __name__ == '__main__':

  logger.setLevel(logging.DEBUG)
  # Uncomment this for sql logs
  # logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

  parser = argparse.ArgumentParser()
  parser.add_argument('-n', action='store')
  args = parser.parse_args()
  Q = SaveQuery()

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
