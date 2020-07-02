#!/usr/bin/python

# ---> Imports
from common import (mkService, s, Labels, MessageInfo,
                    ListMessagesMatchingQuery, DB_NAME,
                    HEADERS, removeMessages, addLabels,
                    removeLabels, WORKING_DIR, logger,
                    updateUserInfo, addMessages)
import pickle
import os.path
import os
import sys
from googleapiclient.http import BatchHttpRequest
from time import sleep

# <---

# ---> Helper functions

def storeLastHistoryId(lastMessageId=None, lastHistoryId=None):
  if lastMessageId:
    q = s.query(MessageInfo).get(lastMessageId)
    with open('lastHistoryId.pickle', 'wb') as f:
      pickle.dump(q.historyId, f)
  elif lastHistoryId:
    with open('lastHistoryId.pickle', 'wb') as f:
      pickle.dump(lastHistoryId, f)


def getLastHistoryId():
  if os.path.exists('lastHistoryId.pickle'):
    with open('lastHistoryId.pickle', 'rb') as f:
      return pickle.load(f)


def ListHistory(service, user_id, start_history_id='1'):
  """List History of all changes to the user's mailbox.

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
  except:
    print('error?')


def updateDb(service, lastHistoryId=None):
  # 100 is maximum size of batch!
  if lastHistoryId is None:
    messageIds = ListMessagesMatchingQuery(mkService(),
                                           'me', query='newer_than:1y')
    addMessages(s, service, [m['id'] for m in messageIds])
    lastMessageId = messageIds[0]['id']
  else:
    changes = ListHistory(mkService(), 'me', getLastHistoryId())
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
    addMessages(s, service, messagesAdded)
    removeMessages(messagesDeleted)
    addLabels(s, labelsAdded)
    removeLabels(s, labelsRemoved)
    try:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
    except:
      lastHistoryId = None
    lastMessageId = None
  s.commit()
  storeLastHistoryId(lastMessageId=lastMessageId, lastHistoryId=lastHistoryId)

# <---

if __name__ == '__main__':
  '''
  # do the UNIX double-fork magic, see Stevens' "Advanced
  # Programming in the UNIX Environment" for details (ISBN 0201563177)
  try:
     pid = os.fork()
     if pid > 0:
         # exit first parent
         sys.exit(0)
  except OSError as e: 
      print (sys.stderr + 'fork #1 failed: %d (%s)' % (e.errno, e.strerror)) 
      sys.exit(1)

  # decouple from parent environment
  os.chdir(WORKING_DIR) 
  os.setsid() 
  os.umask(0) 

  # do second fork
  try: 
      pid = os.fork() 
      if pid > 0:
          # exit from second parent, print eventual PID before
          print ('Daemon PID %d' % pid) 
          sys.exit(0) 
  except OSError as e: 
      print (sys.stderr + 'fork #2 failed: %d (%s)' % (e.errno, e.strerror)) 
      sys.exit(1)

  logger.info('Initialising daemon...')

  # checkerDaemon = DaemonContext() 
  # checkerDaemon.working_directory = WORKING_DIR
  # checkerDaemon.umask = 0o022
  # checkerDaemon.pidfile = WORKING_DIR + '.pid'
  # checkerDaemon.files_preserve = [DB_NAME,'.log']
  # checkerDaemon.detach_process = False

  # logger.info('Working in: ' + WORKING_DIR + ', Database: ' + DB_NAME)

  # with checkerDaemon:
  '''
  while 1:
    updateUserInfo(s, mkService())
    while 1:
      logger.info('Preparing to check for mail...')
      if os.path.exists(DB_NAME):
        logger.info('Performing partial update...')
        updateDb(mkService(), getLastHistoryId())
      else:
        logger.info('Performing full update...')
        updateDb(mkService())
      sleep(300)
    sleep(3600)

"""
vim:foldmethod=marker foldmarker=--->,<---
"""
