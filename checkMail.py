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
                    updateUserInfo, addMessages, UserInfo)
from googleapiclient.http import BatchHttpRequest
from time import sleep

# <---

# ---> Helper functions


def numOfUnreadMessages():
  q1 = s.query(Labels.messageId).filter(Labels.label == 'UNREAD')
  q2 = s.query(Labels.messageId).filter(Labels.label == 'INBOX')
  q = s.query(MessageInfo).filter(
      MessageInfo.messageId.in_(q1),
      MessageInfo.messageId.in_(q2))
  count = q.count()
  logger.info('{} unread emails.'.format(count))
  return count


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

  parser = argparse.ArgumentParser()
  parser.add_argument('-n', action='store_true')
  args = parser.parse_args()

  if args.n == False:
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
  else:
    print(numOfUnreadMessages())


"""
vim:foldmethod=marker foldmarker=--->,<---
"""
