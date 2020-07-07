#!/usr/bin/python

# ---> Imports
from __future__ import print_function
import sys
from datetime import datetime, timezone
import os
import os.path
import re
import pickle
import logging
import yaml
from yaml import Loader
from sqlalchemy import create_engine, desc, UniqueConstraint
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
# <---

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.modify',
          'https://www.googleapis.com/auth/gmail.settings.basic']

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = 'afsec.db'
DB_PATH = 'sqlite:///' + WORKING_DIR + '/' + DB_NAME

HEADERS = ['From', 'Subject', 'To', 'Reply-To', 'In-Reply-To',
           'References', 'Message-ID', 'Content-Type']

logging.basicConfig(filename='.log',
                    level=logging.DEBUG,
                    format='%(asctime)s :: %(levelname)s - %(message)s')

logger = logging.getLogger()

engine = create_engine(DB_PATH)
Base = declarative_base(bind=engine)

session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)
s = Session()

# ---> mkService


def mkService(account):
  with open('config.yaml','r') as f:
      y = yaml.load(f,Loader=Loader)
  credentialsPath = y[account]['credentials']
  tokenPath = os.path.join('tmp/tokens/', account.split('@')[0] + '.pickle')
  creds = None
  # The file token.pickle stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists(tokenPath):
    with open(tokenPath, 'rb') as token:
      creds = pickle.load(token)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
              credentialsPath, SCOPES)
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open(tokenPath, 'wb') as token:
      pickle.dump(creds, token)

  service = build('gmail', 'v1', credentials=creds, cache=MemoryCache())
  return service

# <---

# ---> Class defintions


class MemoryCache(Cache):
  _CACHE = {}

  def get(self, url):
    return MemoryCache._CACHE.get(url)

  def set(self, url, content):
    MemoryCache._CACHE[url] = content


class Attachments(Base):
  __tablename__ = 'attachments'
  id = Column(Integer, primary_key=True)
  messageId = Column(String, ForeignKey('header_info.messageId'))
  partId = Column(String)
  filename = Column(String)
  contentType = Column(String)
  size = Column(Integer)

  def __init__(self, messageId, partId, filename, contentType, size):
    self.messageId = messageId
    self.partId = partId
    self.filename = filename
    self.contentType = contentType
    self.size = size

  def display(self):
    contentType = self.contentType 
    if len(contentType) > 20:
      contentType = contentType[:20]
    elif len(contentType) < 20:
      contentType = contentType + ' ' * (20 - len(contentType))
    display = '{} {} ({}) {}'.format(
      self.partId,
      contentType,
      formatSize(self.size),
      self.filename)
    return display


class AddressBook(Base):
  __tablename__ = 'address_book'
  id = Column(Integer, primary_key=True)
  account = Column(String, ForeignKey('user_info.emailAddress'))
  address = Column(String)
  UniqueConstraint('account', 'address')
  
  def __init__(self, account, address):
    self.account = account
    self.address = address


class UserInfo(Base):
  __tablename__ = 'user_info'
  emailAddress = Column(String, primary_key=True)
  totalMessages = Column(Integer)
  totalThreads = Column(Integer)
  historyId = Column(Integer)
  messages = relationship('MessageInfo', backref='user_info',
                          cascade='all, delete, delete-orphan')
  AddressBook = relationship('AddressBook', backref='user_info',
                          cascade='all, delete, delete-orphan')

  def __init__(self, emailAddress, totalMessages, totalThreads, historyId):
    self.emailAddress = emailAddress
    self.totalMessages = totalMessages
    self.totalThreads = totalThreads
    self.historyId = historyId


class Labels(Base):
  __tablename__ = 'labels'
  id = Column(Integer, primary_key=True)
  messageId = Column(String, ForeignKey('header_info.messageId'))
  label = Column(String)

  def __init__(self, messageId, label):
    self.messageId = messageId
    self.label = label


def formatSize(num):
  for unit in ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
    if abs(num) < 1024.0:
      # return "%3.1f%s%s" % (num, unit, suffix)
      numString = "{:.1f}".format(num)
      lenNumString = len(numString)
      if lenNumString > 4:
        numString = numString[:4]
      elif lenNumString < 4:
        numString = numString + " " * (4 - lenNumString)
      return numString + unit
    num /= 1024.0
  # Unlikely to need this one!
  return "%.1f%s%s" % (num, 'Yi')


def unix2localTime(unix_timestamp):
  utc_time = datetime.fromtimestamp(int(unix_timestamp)//1000, timezone.utc)
  local_time = utc_time.astimezone()
  return local_time.strftime("%b %d")


def unix2localTime2(unix_timestamp):
  utc_time = datetime.fromtimestamp(int(unix_timestamp)//1000, timezone.utc)
  local_time = utc_time.astimezone()
  return local_time.strftime("%a, %b %d, %Y at %-I.%-M %p")


class MessageInfo(Base):

  __tablename__ = 'header_info'
  messageId = Column(String, primary_key=True)
  emailAddress = Column(String, ForeignKey('user_info.emailAddress'))
  historyId = Column(String)
  time = Column(String)
  size = Column(Integer)
  snippet = Column(String)
  externalId = Column(String)
  subject = Column(String)
  sender = Column(String)
  replyTo = Column(String)
  inReplyTo = Column(String)
  references = Column(String)
  recipients = Column(String)
  contentType = Column(String)
  hasAttachments = Column(Boolean)
  labels = relationship('Labels', backref='header_info',
                        cascade="all, delete, delete-orphan")
  attachments = relationship('Attachments', backref='header_info',
                        cascade="all, delete, delete-orphan")

  def __init__(self, messageId, emailAddress, historyId, time, size, 
      snippet, externalId, subject, sender, replyTo, inReplyTo, 
      references, recipients, contentType):
    self.messageId = messageId
    self.emailAddress = emailAddress
    self.historyId = historyId
    self.time = time
    self.size = size
    self.snippet = snippet
    self.externalId = externalId
    self.subject = subject
    self.sender = sender
    self.replyTo = replyTo
    self.inReplyTo = inReplyTo
    self.references = references
    self.recipients = recipients
    self.contentType = contentType 

  def display(self, senderWidth, scrWidth):
    if 'UNREAD' in [l.label for l in self.labels]:
      marker = '\uf0e0 '
      # marker = "*"
    else:
      # marker = '\uf2b7'
      marker = '  '
    if self.existsAttachments():
      attachment = '\uf02b '
    else:
      attachment = '  '
    str = ' {} {} {} ({}) {} {}'.format(
        marker,
        unix2localTime(self.time),
        self.formatName(senderWidth),
        formatSize(self.size),
        attachment,
        self.subject,
        ' ' * scrWidth
        )[:scrWidth]
    return str

  def showLabels(self):
    return [l.label for l in self.labels]

  def timeForReply(self):
    return unix2localTime2(self.time)

  def parseSender(self):
    try:
      email = re.search('\<(.*?)\>', self.sender).group(1)
    except:
      email = self.sender
    name = re.sub(' \<(.*?)\>', '', self.sender)
    return email, name

  def formatName(self, senderWidth):
    name = self.parseSender()[1]
    name = re.sub('"', '', name)
    if len(name) < senderWidth:
      name = name + ' ' * (senderWidth - len(name))
    else:
      name = name[:senderWidth]
    return name

  def existsAttachments(self):
    '''
    Try to figure out if there are attachments from the content-type
    header. This can return false positives. 
    To deal with this if at some later stage (usually, when trying to view 
    attachments) it is found that really there were no attachments, the 
    hasAttachments attribute gets updated to False.
    '''
    if self.hasAttachments == False:
      return self.hasAttachments
    else:
      try:
        s = re.search('multipart/mixed',self.contentType) 
      except:
        s = False
      if s == None:
        return False
      else:
        return True


# Only needed to create table structure
Base.metadata.create_all()
# <---

# ---> Other functions


def addMessage(account, session, msg):
  headers = dict(zip(HEADERS, [None for i in range(len(HEADERS))]))
  for h in msg['payload']['headers']:
    name = h['name']
    for n in HEADERS:
      if name.lower() == n.lower():
        headers[n] = h['value']

    # if name == 'Subject':
    #     subject = h['value']
    # elif name == 'From':
    #     sender = h['value']
    # elif name == 'To':
    #     recipients = h['value']

  try:
    labels = [Labels(msg['id'], label) for label in msg['labelIds']]
    # logger.info(str([l for l in msg['labelIds']]))
    session.add_all(labels)
  except KeyError:
    logger.debug('Could not add: ' + str(msg))
    logger.debug("Adding label ['UNCLASSIFIED']")
    session.add(Labels(msg['id'],'UNCLASSIFIED'))
  if headers['From']:
    header = MessageInfo(
        msg['id'],
        account,
        msg['historyId'],
        msg['internalDate'],
        msg['sizeEstimate'],
        msg['snippet'],
        headers['Message-ID'],
        headers['Subject'],
        headers['From'],
        headers['Reply-To'],
        headers['In-Reply-To'],
        headers['References'],
        headers['To'],
        headers['Content-Type'])
    session.add(header)
    logger.debug('Adding header to db')
  else:
    logger.debug(str(headers))
    logger.debug(str(msg))


def addMessages(session, account, service, messageIds):
  def doesMessageAlreadyExist(messageId):
    q = session.query(MessageInfo).filter(MessageInfo.messageId == messageId)
    if q.first():
      return False 
    else:
      return True
  q = list(filter(doesMessageAlreadyExist, messageIds))
  i, l, batch = 0, len(q), service.new_batch_http_request()
  logger.debug('Making batch request..')
  while i < l:
    for messageId in q[i:i+100]:
      batch.add(service.users().messages().get(
          userId='me',
          id=messageId,
          format='metadata',
          metadataHeaders=HEADERS
      ), callback=(lambda x, y, z: _updateDb(session, account, x, y, z)))
    batch.execute()
    batch = service.new_batch_http_request()
    i += 100


def _updateDb(session, account, requestId, response, exception):
  if exception is not None:
    logger.debug(exception)
    # Do something with the exception
    # See BatchHttpRequest docs
  else:
    # Parse headers.
    addMessage(account, session, response)


def ListMessagesMatchingQuery(service, user_id, query=''):
  """List all Messages of the user's mailbox matching the query.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    query: String used to filter messages returned.
    Eg.- 'from:user@some_domain.com' for Messages from a particular sender.

  Returns:
    List of Messages that match the criteria of the query. Note that the
    returned list contains Message IDs, you must use get with the
    appropriate ID to get the details of a Message.
  """
  try:
    response = service.users().messages().list(userId=user_id,
                                               q=query).execute()
    messages = []
    if 'messages' in response:
      messages.extend(response['messages'])

    while 'nextPageToken' in response:
      page_token = response['nextPageToken']
      response = service.users().messages().list(userId=user_id, q=query,
                                                 pageToken=page_token).execute()
      messages.extend(response['messages'])

    return messages
  except:
    print('An error occurred')

def countAttachments(message):
  c = 0
  if 'payload' in message:
    if 'parts' in message['payload']:
      for part in message['payload']['parts']:
        if part['filename']:
          c+=1
      return c 
    else:
      return 0
  else:
    return 0


def myEmail(service):
  return (service.users().getProfile(userId='me').execute())['emailAddress']


def updateUserInfo(session, service):
  profile = service.users().getProfile(userId='me').execute()
  emailAddress = profile['emailAddress']
  messagesTotal = profile['messagesTotal']
  threadsTotal = profile['threadsTotal']
  historyId = profile['historyId']
  userInfo = UserInfo(emailAddress, messagesTotal, threadsTotal, historyId)
  q = session.query(UserInfo)
  if q.first():
    session.query(UserInfo).update(
        {UserInfo.totalMessages: messagesTotal,
         UserInfo.totalThreads: threadsTotal,
         UserInfo.historyId: historyId}, synchronize_session=False)
  else:
    session.add(userInfo)


def removeMessages(messageIds):
  s.query(MessageInfo).filter(MessageInfo.messageId in
                             messageIds).delete(synchronize_session='fetch')


def addLabels(session, labels):
  for (messageId, ls) in labels:
    for l in ls:
      label = Labels(messageId, l)
      session.add(label)


def removeLabels(session, labels):
  for (messageId, ls) in labels:
    session.query(Labels).filter(Labels.messageId == messageId, Labels.label.in_(ls))\
        .delete(synchronize_session=False)

def listAccounts():
  with open('config.yaml','r') as f:
      y = yaml.load(f,Loader=Loader)
  return y.keys() 


def getName(myemail):
  with open('config.yaml','r') as f:
      y = yaml.load(f,Loader=Loader)
  return y[myemail]['name']

def addressList(myemail):
  q = s.query(AddressBook).filter(AddressBook.account == myemail)
  for address in q:
    yield address.address


def mkAddressBook(account):
  # Could make this more effecient!
  query = s.query(MessageInfo).filter(MessageInfo.emailAddress == account)
  seen = set()
  for q in query:
    if q.sender in seen:
      continue
    else:
      seen.add(q.sender)
    try:
      all = filter(lambda x: not re.search(account,x), 
              (q.recipients).split(','))  
    except: 
      pass
    for a in all:
      if a in seen:
        continue
      else:
        seen.add(a)
  s.query(AddressBook).delete()
  s.commit()
  
  addresses = []
  for a in seen:
    if not s.query(AddressBook).filter(AddressBook.address == a).first():
      addresses.append(AddressBook(account,a))
  s.add_all(addresses)
  s.commit()

# <---
"""
vim:foldmethod=marker foldmarker=--->,<---
"""
