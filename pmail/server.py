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
from pmail.common import (mkService, Session, Labels, MessageInfo,
                    listMessagesMatchingQuery, logger,
                    UserInfo, AddressBook, config)
from googleapiclient.http import BatchHttpRequest
from threading import Thread, Lock, Event
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
  # logger.info('Storing last historyId: {}'.format(lastHistoryId))
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


def getLastHistoryId(account, session):
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


def updateDb(account, session, service, newMessagesArrived, lastHistoryId=None):
  '''
  Update the Database with messages since lastHistoryId.

  Args:
    account: The account which the messages come from.
    session: DB session.
    service: The google API sevice object.
    lastHistoryId: The historyId of the last update, if there was one.

  Returns:
    historyId corresponding to this update.
  '''
  # 100 is maximum size of batch!
  if lastHistoryId is None:
    messageIds = listMessagesMatchingQuery(service(account),
                                           'me', query='newer_than:' + config.syncFrom)
    MessageInfo.addMessages(session, account,
                            service(account), [m['id'] for m in messageIds])
    lastMessageId = messageIds[0]['id']
    # logger.info('lastMessageId: {}'.format(lastMessageId))

  else:
    changes = ListHistory(service(account), 'me',
                          getLastHistoryId(account, session))
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
    if len(messagesAdded) > 0:
      # Set newMessagesArrived to be true, this will cause the Cache
      # (savedQuery) to be updated.
      logger.info('There are new messages!')
      newMessagesArrived.set()

    MessageInfo.removeMessages(session, messagesDeleted)
    Labels.addLabels(session, labelsAdded)
    Labels.removeLabels(session, labelsRemoved)
    # try:
    if len(changes) > 0:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
      # logger.info('Last history id: {}'.format(lastHistoryId))
    else:
    # except Exception as e:
      # logger.debug(e)
      lastHistoryId = None
    lastMessageId = None
  # storeLastHistoryId(account, session, lastMessageId=lastMessageId,
  #                    lastHistoryId=lastHistoryId)
  if lastMessageId:
    lastHistoryId = session.query(MessageInfo).get(lastMessageId).historyId
    # logger.info('lastHistoryId: {}'.format(lastHistoryId))
  return lastHistoryId

# <---

# ---> Server Functions


def getMessages(s, Q, newMessagesArrived, account, query, position,
                height, excludedLabels=[],
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
  if newMessagesArrived.is_set():
    logger.info('New messages arrived, refreshing the cache.')
    q = Q.getQuery(s, account, query, includedLabels,
                   excludedLabels, refresh=True)
    newMessagesArrived.clear()
  elif afterAction == None:
    q = Q.getQuery(s, account, query, includedLabels, excludedLabels)
  elif afterAction['action'] in ['DELETE', 'TRASH']:
    logger.info('Removing message: {} from cache.'
                .format(afterAction['messageIds']))
    q = Q.removeMessages(afterAction['messageIds'])
  elif afterAction['action'] in ['MARK_AS_READ']:
    # logger.info('removing msg from cache')
    logger.info('Refreshing the cache, after reading.')
    # q = Q.markAsRead(afterAction['messageIds'])
    q = Q.getQuery(s, account, query, includedLabels,
                   excludedLabels, refresh=True)
  if count == False:
    # return [h for h in q.slice(position, position + height - 2)]
    return q[position:position + height - 2]
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

  def getQuery(self, s, account, query, includedLabels, excludedLabels, refresh=False):
    # Also deletes, new mails, mark as read, etc..
    # logger.info("read :{}.".format(read))
    if (self.account == account and
        str(self.query) == str(query) and
        self.includedLabels == includedLabels and
            self.excludedLabels == excludedLabels) and refresh == False:
      # logger.info('Using saved query.')
      return self.savedQuery
    else:
      excludeQuery = s.query(Labels.messageId).filter(
          Labels.label.in_(excludedLabels))
      includeQuery = s.query(Labels.messageId).filter(
          Labels.label.in_(includedLabels))
      # logger.info('Made two queries.')
      q = s.query(MessageInfo)\
          .filter(
              MessageInfo.messageId.in_(query),
              MessageInfo.emailAddress == account,
              ~MessageInfo.messageId.in_(excludeQuery),
              MessageInfo.messageId.in_(includeQuery))\
          .order_by(MessageInfo.time.desc())
      # logger.info('Successfully(?) refreshed the cache.')
      self.account = account
      self.query = query
      self.includedLabels = includedLabels
      self.excludedLabels = excludedLabels
      self.savedQuery = list(q)
      # logger.info('Generating new query.')
      return self.savedQuery

  def removeMessages(self, messageIds):
    self.savedQuery = [m for m in self.savedQuery if m.messageId not in
                       messageIds]
    return self.savedQuery

  # This didn't work - probably remove it later
  def markAsRead(self, messageIds):
    logger.info('Marking as read.')
    newSavedQuery = []
    for m in self.savedQuery:
      logger.info('trying')
      if m.messageId in messageIds:
        logger.info('Found message with labels: {}'
                    .format(m.labels))
        m.labels = [l.label for l in m.labels if l.label != 'UNREAD']
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


def pmailServer(lock, newMessagesArrived, Q):
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
      logger.info('Listening on port {}.'
                  .format(config.port))
    except OSError as e:
      logger.info(e)
      logger.warning('Port {} busy. Checking port again in 30s.'
                  .format(config.port))
      sleep(30)

  s = Session()

  # configure how many client the server can listen simultaneously
  # only accept connections from client?
  sock.listen(1)
  while 1:
    conn, address = sock.accept()
    print("Connection from: {}.".format(str(address)))
    sizeOfIncoming = int.from_bytes(conn.recv(4), 'big')
    print(sizeOfIncoming)
    incoming = b''

    while len(incoming) < sizeOfIncoming:
      incoming += conn.recv(bufferSize)

    unpickledIncoming = pickle.loads(incoming, encoding='bytes')

    # Do something and return a response.
    action = unpickledIncoming['action']
    with lock:
      if action == 'CHECK_FOR_NEW_MESSAGES':
        if newMessagesArrived.is_set():
          response = 'newMessagesArrived'
          # newMessagesArrived.clear()
        else:
          response = 'noNewMessages'
      elif action == 'GET_MESSAGES':
        # Get messages.
        incomingQ = unpickledIncoming['query']
        query = s.query(
            MessageInfo.messageId) if incomingQ is None else incomingQ
        # logger.info('afterAction: {}'.format(unpickledIncoming['afterAction']))
        response = getMessages(s,
                               Q,
                               newMessagesArrived,
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
        response = [e for e in s.query(cls)
                    .filter(cls.messageId.in_(messageIds))]
      elif action == 'REMOVE_LABELS':
        # logger.info('Removing labels...')
        # Remove labels.
        # logger.info('Recieved instructions from client'
        #             + '{}'.format(unpickledIncoming))
        labels = unpickledIncoming['labels']
        Labels.removeLabels(s, labels)
        try:
          account = unpickledIncoming['account']
          incomingQ = unpickledIncoming['query']
          query = s.query(
              MessageInfo.messageId) if incomingQ is None else incomingQ
          # query = unpickledIncoming['query']
          includedLabels = unpickledIncoming['includedLabels']
          excludedLabels = unpickledIncoming['excludedLabels']
          # logger.info('Refreshing saved query.')
          Q.getQuery(s, account, query, includedLabels,
                     excludedLabels, refresh=True)
        except Exception as e:
          logger.warning(e)
        response = None
        # response = Q.markAsRead([l[0] for l in labels])
      elif action == 'ADD_LABELS':
        # Add labels.
        # logger.info('Recieved instructions from client'
        #             + '{}'.format(unpickledIncoming))
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

    # if action == 'REMOVE_LABELS':
    #   for account in config.listAccounts():
    #     UserInfo.update(s, account, None, None)
    s.commit()
    s.close()
    print('closing connection..')
    conn.close()


def syncDb(lock, newMessagesArrived):
  s = Session()
  while 1:
    try:
      with lock:
        logger.info('Acquired lock, making session.')
        for account in config.listAccounts():
          shouldIupdate = s.query(UserInfo).get(account)
          # logger.info('shouldIupdate: {}'.format(shouldIupdate))
          # logger.info('shouldIupdate.shouldIupdate: {}'
          #              .format(shouldIupdate.shouldIupdate))

          if shouldIupdate and shouldIupdate.shouldIupdate == False:
            # logger.info('Performing partial update for {}.'.format(account))
            lastHistoryId = updateDb(account, s, mkService,
                                     newMessagesArrived, getLastHistoryId(account, s))
            UserInfo.update(s, account, None, lastHistoryId)
            logger.info('Successful partial update for {}.'.format(account))

          elif shouldIupdate is None or shouldIupdate.shouldIupdate == True:
            # logger.info('Performing full update for {}.'.format(account))
            lastHistoryId = updateDb(account, s, mkService, newMessagesArrived)
            UserInfo.update(s, account, mkService(account), lastHistoryId)
            UserInfo.succesfulUpdate(s, account)
            logger.info('Successful full update for {}.'.format(account))
            with open(os.path.join(config.pickleDir,
                                   'synced.pickle'), 'wb') as f:
              pickle.dump(False, f)
      s.close()
    except Exception as e:
      logger.warning(e)
      logger.info('Unable to update DB, trying again soon.')
    except KeyboardInterrupt as k:
      print("Bye!")
      logger.info(k)
      sys.exit()
    sleep(config.updateFreq)


# if __name__ == '__main__':
def start():
  logger.setLevel(logging.DEBUG)
  # Uncomment this for sql logs
  # logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

  # parser = argparse.ArgumentParser()
  # parser.add_argument('-n', action='store')
  # args = parser.parse_args()
  Q = SaveQuery()

  # if args.n == None:
  lock = Lock()
  newMessagesArrived = Event()
  t1 = Thread(target=pmailServer, 
              args=(lock, newMessagesArrived, Q),
              daemon=True)
  t2 = Thread(target=syncDb, args=(lock, newMessagesArrived,))
  t1.start()
  t2.start()

def checkForNewMessages(id):
  for k in config.listAccounts():
    if config.accounts[k]['id'] == id:
      account = k
  s = Session()
  q = s.query(UserInfo.numOfUnreadMessages)\
      .filter(UserInfo.emailAddress == account)
  Session.remove()
  return(q[0][0])

# <---

"""
vim:foldmethod=marker foldmarker=--->,<---
"""
