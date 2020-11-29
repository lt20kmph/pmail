#!/usr/bin/python

# ---> Imports

import json
import pickle
import os.path
import os
import sys
import socket
# import logging
# import argparse

# from apiclient import errors
from pmail.common import (mkService, Session, Labels, MessageInfo,
                          listMessagesMatchingQuery, logger,
                          UserInfo, config, setupAttachments, LabelInfo)
from pmail.subscriber import subscribe
# from googleapiclient.errors import HttpError
# from googleapiclient.http import BatchHttpRequest
from threading import Thread, Lock, Event
from time import sleep, time
from queue import Queue, Empty

# <---

# ---> DB update and synchronisation


# ---> last History

def storeLastHistoryId(account, session, lastMessageId=None, lastHistoryId=None):
  '''
  Store the last historyId as part of UserInfo, for use when updating the db.

  Args:
    session: db session.
    account: Account whose history we are storing.
    lastMessageId = The id of the last message saved in the db.
    lastHistoryId = The lastHistoryId.

  Returns:
    None
  '''
  if lastMessageId:
    lastHistoryId = session.query(MessageInfo).get(lastMessageId).historyId
    q = session.query(UserInfo).get(account)
    q.historyId = lastHistoryId
    session.commit()
  elif lastHistoryId:
    q = session.query(UserInfo).get(account)
    q.historyId = lastHistoryId
    session.commit()


def getLastHistoryId(account, session):
  '''
  Get the last history for account from the pickle if it exists.
  Args:
    session: db session.
  Returns:
    The last history id.
  '''
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
  except Exception:
    logger.exception('An error occured while trying to list history.')

# <---


def updateDb(account,
             session,
             service,
             newMessagesArrived,
             lastHistoryId=None):
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
    LabelInfo.addLabels(session, account)
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

      if config.afterUnreadChange:
        os.system(config.afterUnreadChange)

    MessageInfo.removeMessages(session, messagesDeleted)
    Labels.addLabels(session, labelsAdded)
    Labels.removeLabels(session, labelsRemoved)
    LabelInfo.addLabels(session, account)

    if len(changes) > 0:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
    else:
      lastHistoryId = None
    lastMessageId = None

  if lastMessageId:
    lastHistoryId = session.query(MessageInfo).get(lastMessageId).historyId
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
  elif afterAction is None:
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
  if count is False:
    # return [h for h in q.slice(position, position + height - 2)]
    return q[position:position + height - 2]
  elif count is True:
    # return q.count()
    return len(q)


class SaveQuery():
  '''
  Class which acts as a cache so that the db does not need to be queried
  unnessessairly. The main reason this is needed is to ensure that scolling
  remains smooth, untested with really large numbers of messages (>6000). If
  the number of messages gets too large this might need refinements.
  '''

  def __init__(self):
    self.account = None
    self.query = None
    self.includedLabels = None
    self.excludedLabels = None
    # self.savedQuery: List of messages mathing query - i.e. the evaluated
    # query.
    self.savedQuery = None

  def getQuery(self, s, account, query, includedLabels,
               excludedLabels, refresh=False):
    '''
    Method to getQuery, checks if any of the parameters has changed, if not
    then it just uses the cached query, if something changed then we ask the
    db.
    Args:
      s: db session.
      account: The account which we need to get a query for.
      query: This is a db query, possibly resulting from doing a search.
      includedLabels: List consisting of lables to include.
      excludedLabels: List consisting of labels to exclude.
      refresh: If true then we ask the db no matter what, this is incase new
      messages showed up or messages got deleted etc...
    Returns:
      List of messages mathcing query.
    '''
    # logger.info("read :{}.".format(read))
    if (self.account == account and
        str(self.query) == str(query) and
        self.includedLabels == includedLabels and
            self.excludedLabels == excludedLabels) and refresh == False:
      logger.info('Using saved query.')
      return self.savedQuery
    else:
      excludeQuery = s.query(Labels.messageId).filter(
          Labels.labelId.in_(excludedLabels))
      includeQuery = s.query(Labels.messageId).filter(
          Labels.labelId.in_(includedLabels))
      # logger.info('Made two queries.')
      if account:
        q = s.query(MessageInfo)\
            .filter(
                MessageInfo.messageId.in_(query),
                MessageInfo.emailAddress == account,
                ~MessageInfo.messageId.in_(excludeQuery),
                MessageInfo.messageId.in_(includeQuery))\
            .order_by(MessageInfo.time.desc())
      else:
        q = s.query(MessageInfo)\
            .filter(
                MessageInfo.messageId.in_(query),
                ~MessageInfo.messageId.in_(excludeQuery),
                MessageInfo.messageId.in_(includeQuery))\
            .order_by(MessageInfo.time.desc())
      # logger.info('Successfully(?) refreshed the cache.')
      self.account = account
      self.query = query
      self.includedLabels = includedLabels
      self.excludedLabels = excludedLabels
      self.savedQuery = list(q)
      logger.info('Generating new query.')
      return self.savedQuery

  def removeMessages(self, messageIds):
    '''
    Method to remove messages from the cache.
    Args:
      messageIds: List of messageIds which we should remove.
    Returns:
      New list of messages.
    '''
    self.savedQuery = [m for m in self.savedQuery if m.messageId not in
                       messageIds]
    return self.savedQuery

  '''
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

# <---

# ---> Main


def pmailServer(lock, newMessagesArrived, Q):
  '''
  Function which gets run by the server thread.
  Args:
    lock: threading.Lock()
    newMessagesArrived: threading.Event()
    Q: SaveQuery()
  Returns:
    None
  '''
  host = socket.gethostname()
  port = config.port
  bufferSize = 1024

  portFree = True
  while portFree is True:
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
      # logger.info('Server aquired the lock.')
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
        except KeyError:
          pass
        # except Exception:
        #   logger.exception('Something unexpected happened.')
        response = None
        # response = Q.markAsRead([l[0] for l in labels])
      elif action == 'ADD_LABELS':
        # Add labels.
        # logger.info('Recieved instructions from client'
        #             + '{}'.format(unpickledIncoming))
        labels = unpickledIncoming['labels']
        Labels.addLabels(s, labels)
        response = None
      # elif action == 'REMOVE_FALSE_ATTACMENTS':
      #   # Remove false attachments.
      #   messageId = unpickledIncoming['messageId']
      #   s.query(MessageInfo).filter(MessageInfo.messageId == messageId)\
      #       .update({MessageInfo.hasAttachments: False},
      #               synchronize_session='evaluate')
      elif action == 'GET_LABEL_MAP':
        # Get the labelMap - this feels a bit hacky...
        labelMap = LabelInfo.getName(s)
        # logger.info(labelMap)
        response = labelMap

    pickledResponse = pickle.dumps(response)
    sizeOfPickle = len(pickledResponse)
    numOfChunks = sizeOfPickle // bufferSize + 1
    conn.send(sizeOfPickle.to_bytes(4, 'big'))

    for i in range(numOfChunks):
      conn.send(pickledResponse[i * bufferSize: (i + 1) * bufferSize])

    # if action == 'REMOVE_LABELS':
    #   for account in config.listAccounts():
    #     UserInfo.update(s, account, None, None)
    s.commit()
    # logger.info('Closing database connection.')
    s.close()
    # logger.info('Closing socket connection.')
    print('closing connection..')
    conn.close()


'''
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
    except Exception:
      logger.exception('Unable to update DB, trying again soon.')
    # TODO: this doesn't work as expected.
    except KeyboardInterrupt as k:
      print("Bye!")
      logger.info(k)
      sys.exit()
    sleep(config.updateFreq)
'''


class ClearableQueue(Queue):
  '''
  Add an extra clear method to Queue, because we will want to empty it put
  after retriving something, incase a lot of items built up.

  '''

  def clear(self):
    try:
      while True:
        self.get_nowait()
    except Empty:
      pass


def _syncDb_pubsub(session, pubSubQue, newMessagesArrived, lock, futures):
  '''
  Function which gets called by the syncer if update_policy is set to
  'pubsub'.
  Args:
    session: db session.
    pubSubQue: ClearableQueue
    account: Account which is being synched.
    newMessagesArrived: threading.Event()
    futures: a dictonary of
    google.cloud.pubsub_v1.subscriber.StreamingPullFuture objects,
    one corresponding to each account.
  Returns:
    futures: a dictonary of
    google.cloud.pubsub_v1.subscriber.StreamingPull objects,
    one corresponding to each account.
  '''
  for account in config.listAccounts():
    # Check watch request has not expired.
    ui = session.query(UserInfo).get(account)
    if not ui:
      logger.info('Userinfo for: {} does not exist.'.format(account))
      ui = UserInfo(account)
      setupAttachments(account)
      with lock:
        logger.info('Sync function acquired lock. About to sync.')
        session.add(ui)
        session.commit()
        logger.info('Created user info for: {}'.format(account))
    if (not ui.watchExpirey) or \
       (ui.watchExpirey < (int(time()) - 24 * 60 * 60) * 1000):
      logger.info('Watch does not exist or is about to expire so rewatching.')
      service = mkService(account)
      service.users().stop(userId='me')
      request = {
          'labelIds': ['INBOX'],
          'topicName': 'projects/{}/topics/pmail'.format(
              config.accounts[account]['project_id']
          )}
      response = service.users().watch(userId='me', body=request).execute()
      ui.watchExpirey = response['expiration']
      with lock:
        logger.info('Sync function acquired lock. About to sync.')
        session.commit()

    # Subscribe to pubsub topic.
    if not futures[account] or not futures[account].running():
      logger.info('Subscribing to pubsub topic for: {}'.format(account))
      futures[account] = subscribe(pubSubQue, account)

  try:
    # Blocks until something is in the queue to get or timeout is reached.
    m = pubSubQue.get(timeout=60 * 60 * 12)
    # Clear the queue in case multiple messages built up.
    pubSubQue.clear()
    account = json.loads(m.decode('utf-8'))['emailAddress']
    logger.info('There was in change in: {}'.format(account))
    with lock:
      logger.info('Sync function acquired lock. About to sync.')
      __syncDb(session, account, newMessagesArrived)
      return futures
  except Empty:
    logger.info('Nothing detected, but updating anyway just in case.')
    with lock:
      logger.info('Sync function acquired lock. About to sync.')
      for account in config.listAccounts():
        __syncDb(session, account, newMessagesArrived)
      return futures
  except Exception:
    logger.exception('Error while getting something from the pubsub queue.')


def _syncDb_freq(session, newMessagesArrived, lock):
  '''
  Function which gets called by the sync thread if update_policy is set to
  frequency.
  Args:
    session: db session.
    account: Account which is being synched.
    newMessagesArrived: threading.Event()
  Returns:
    None
  '''
  for account in config.listAccounts():
    # Check user info exists.
    ui = session.query(UserInfo).get(account)
    if not ui:
      logger.info('Userinfo for: {} does not exist.'.format(account))
      ui = UserInfo(account)
      setupAttachments(account)
      with lock:
        logger.info('Sync function acquired lock. About to sync.')
        session.add(ui)
        session.commit()
        logger.info('Created user info for: {}'.format(account))
  try:
    with lock:
      logger.info('Sync function acquired lock. About to sync.')
      for account in config.listAccounts():
        __syncDb(session, account, newMessagesArrived)
  except Exception:
    logger.exception('Error while trying to sync local DB.')
  sleep(config.updateFreq)


def __syncDb(session, account, newMessagesArrived):
  '''
  Function which actually perfroms the sync, inner most function of the loop.
  Args:
    session: db session.
    account: Account which is being synched.
    newMessagesArrived: threading.Event()
  Returns:
    None
  '''
  ui = session.query(UserInfo).get(account)
  if ui.shouldIupdate is False:
    lastHistoryId = updateDb(account, session, mkService,
                             newMessagesArrived, getLastHistoryId(account,
                                                                  session))
    ui.update(session, account, None, lastHistoryId)
    logger.info('Successful partial update for {}.'.format(account))

  elif ui.shouldIupdate is True:
    ui.shouldIupdate = False
    lastHistoryId = updateDb(account, session, mkService, newMessagesArrived)
    ui.update(session, account, mkService(account), lastHistoryId)
    # UserInfo.succesfulUpdate(session, account)
    logger.info('Successful full update for {}.'.format(account))
    with open(os.path.join(config.pickleDir, 'synced.pickle'), 'wb') as f:
      pickle.dump(False, f)
  session.close()


def syncDb(lock, newMessagesArrived):
  '''
  Function to keep local db in sync with remote db (gmail).
  Args:
    lock: threading.Lock() object, to prevent race conditions on local db.
    newMessagesArrived: threading.Event() object, so that the server can be
    notified when the syncher detects something new.
  Returns:
    None
  '''
  s = Session()
  pubSubQue = ClearableQueue()
  futures = {}
  for account in config.listAccounts():
    futures[account] = None
  while 1:
    try:
      if config.updatePolicy == 'pubsub':
        futures = _syncDb_pubsub(
            s, pubSubQue, newMessagesArrived, lock, futures)
      elif config.updatePolicy == 'frequency':
        _syncDb_freq(s, newMessagesArrived, lock)
      else:
        print('Error, update_policy seems incorrectly configured.')
        sys.exit()
    # TODO: this doesn't work as expected.
    except KeyboardInterrupt as k:
      print("Bye!")
      logger.info(k)
      sys.exit()
    except Exception:
      logger.exception('Unable to update DB, trying again soon.')


# if __name__ == '__main__':
def start():
  '''
  Start both the server thread and a thread which will update the local db.
  '''
  logger.setLevel(config.logLevel)
  # Uncomment this for sql logs
  # logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

  lock = Lock()
  newMessagesArrived = Event()
  t1 = Thread(target=pmailServer,
              args=(lock, newMessagesArrived, SaveQuery()),
              daemon=True)
  t2 = Thread(target=syncDb, args=(lock, newMessagesArrived,))
  t1.start()
  t2.start()


def checkForNewMessages(id):
  '''
  Function to be run by external programs to check if there are unread
  messages.

  Args:
    id: this is the short id of the account as set in the accounts setting of
    the config file.
  Returns:
    The number of unread messages for the account corresponding to id.
  '''
  s = Session()
  for k in config.listAccounts():
    if config.accounts[k]['id'] == id:
      account = k
  numOfUnreadMessages = UserInfo._numOfUnreadMessages(s, account)
  Session.remove()
  return numOfUnreadMessages

# <---


"""
vim:foldmethod=marker foldmarker=--->,<---
"""
