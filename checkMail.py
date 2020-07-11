#!/usr/bin/python

# ---> Imports

import pickle
import os.path
import os
import sys
import argparse

from apiclient import errors
from common import (mkService, s, Labels, MessageInfo,
                    listMessagesMatchingQuery,
                    logger, UserInfo,
                    AddressBook, config)
from googleapiclient.http import BatchHttpRequest
from time import sleep

# <---

# ---> Number of unread messages


def numOfUnreadMessages(account):
  '''
  Get the number of unread messages in the INBOX.

  Args:
    account: The account to query.
  Returns: An integer.
  '''
  q1 = s.query(Labels.messageId).filter(Labels.label == 'UNREAD')
  q2 = s.query(Labels.messageId).filter(Labels.label == 'INBOX')
  q = s.query(MessageInfo).filter(
      MessageInfo.emailAddress == account,
      MessageInfo.messageId.in_(q1),
      MessageInfo.messageId.in_(q2))
  count = q.count()
  return count

# <---

# ---> DB update and synchronisation


# ---> Pickling

def storeLastHistoryId(account, lastMessageId=None, lastHistoryId=None):
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
    q = s.query(MessageInfo).get(lastMessageId)
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


def updateDb(account, service, lastHistoryId=None):
  '''
  Update the Database with messages since lastHistoryId.

  Args: 
    account: The account which the messages come from.
    service: The google API sevice object.

  Returns:
    None.
  '''
  # 100 is maximum size of batch!
  if lastHistoryId is None:
    messageIds = listMessagesMatchingQuery(service(account),
         'me', query='newer_than:' + config.syncFrom)
    MessageInfo.addMessages(s, account, service(account), [m['id'] for m in messageIds])
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
    MessageInfo.addMessages(s, account, service(account), messagesAdded)
    MessageInfo.removeMessages(messagesDeleted)
    Labels.addLabels(s, labelsAdded)
    Labels.removeLabels(s, labelsRemoved)
    try:
      lastHistoryId = str(max([int(change['id']) for change in changes]))
    except:
      lastHistoryId = None
    lastMessageId = None
  s.commit()
  storeLastHistoryId(account, lastMessageId=lastMessageId,
                     lastHistoryId=lastHistoryId)

# <---

# ---> Main
if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  parser.add_argument('-n', action='store')
  args = parser.parse_args()

  if args.n == None:
    while 1:
      for account in config.listAccounts():
        UserInfo.update(s, mkService(account))
      while 1:
        for account in config.listAccounts():
          logger.info('Preparing to check for mail...')
          # if os.path.exists(config.dbPath):
          if config.dbExists is True:
            logger.info('Performing partial update...')
            updateDb(account, mkService, getLastHistoryId(account))
          elif config.dbExists is False:
            logger.info('Performing full update...')
            updateDb(account, mkService)
            config.dbExists = True
        sleep(config.updateFreq)
      sleep(3600)
  else:
    print(numOfUnreadMessages(args.n))

# <---

"""
vim:foldmethod=marker foldmarker=--->,<---
"""
