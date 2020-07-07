#!/usr/bin/python

# ---> Imports
import pickle
import os.path
import os
import sys
import argparse

from common import (mkService, s, Labels, MessageInfo,
                    ListMessagesMatchingQuery, DB_NAME,
                    HEADERS, removeMessages, addLabels,
                    removeLabels, WORKING_DIR, logger,
                    updateUserInfo, addMessages, UserInfo,
                    listAccounts, mkAddressBook)
from googleapiclient.http import BatchHttpRequest
from time import sleep

# <---

# ---> Helper functions
PICKLE_DIR = 'tmp/pickles'

def numOfUnreadMessages(account):
  q1 = s.query(Labels.messageId).filter(Labels.label == 'UNREAD')
  q2 = s.query(Labels.messageId).filter(Labels.label == 'INBOX')
  q = s.query(MessageInfo).filter(
      MessageInfo.emailAddress == account,
      MessageInfo.messageId.in_(q1),
      MessageInfo.messageId.in_(q2))
  count = q.count()
  logger.info('{} unread emails.'.format(count))
  return count


def storeLastHistoryId(account, lastMessageId=None, lastHistoryId=None):
  path = os.path.join(PICKLE_DIR,'lastHistoryId.' + account + '.pickle')
  if lastMessageId:
    q = s.query(MessageInfo).get(lastMessageId)
    with open(path, 'wb') as f:
      pickle.dump(q.historyId, f)
  elif lastHistoryId:
    with open(path, 'wb') as f:
      pickle.dump(lastHistoryId, f)


def getLastHistoryId(account):
  path = os.path.join(PICKLE_DIR,'lastHistoryId.' + account + '.pickle')
  if os.path.exists(path):
    with open(path,'rb') as f:
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


def updateDb(account, service, lastHistoryId=None):
  # 100 is maximum size of batch!
  if lastHistoryId is None:
    messageIds = ListMessagesMatchingQuery(service(account),
                                           'me', query='newer_than:6m')
    addMessages(s, account, service(account), [m['id'] for m in messageIds])
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
    addMessages(s, account, service(account), messagesAdded)
    removeMessages(messagesDeleted)
    addLabels(s, labelsAdded)
    removeLabels(s, labelsRemoved)
    try:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
    except:
      lastHistoryId = None
    lastMessageId = None
  s.commit()
  storeLastHistoryId(account, lastMessageId=lastMessageId, lastHistoryId=lastHistoryId)

# <---


if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  parser.add_argument('-n', action='store')
  args = parser.parse_args()

  if args.n == None:
    while 1:
      for account in listAccounts():
        updateUserInfo(s, mkService(account))
      while 1:
        for account in listAccounts():
          logger.info('Preparing to check for mail...')
          if os.path.exists(DB_NAME):
            logger.info('Performing partial update...')
            updateDb(account, mkService, getLastHistoryId(account))
          else:
            logger.info('Performing full update...')
            updateDb(account, mkService)
          mkAddressBook(account)
        sleep(300)
      sleep(3600)
  else:
    print(numOfUnreadMessages(args.n))


"""
vim:foldmethod=marker foldmarker=--->,<---
"""
