#!/usr/bin/python

"""Send an email message from the user's account.
"""

# ---> Imports
import re
import base64
import mimetypes
import os

from apiclient import errors
from common import logger, getName
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
# <---


def sendMessage(service, userId, message):
  """Send an email message.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    message: Message to be sent.

  Returns:
    Sent Message.
  """
  try:
    message = (service.users().messages().\
        send(userId=userId, body=message).execute())
    # print('Message Id: %s' % message['id'])
    return message
  except errors.Error as e:
    logger.warning(e)

'''
def createForward(myemail, to, header, messageText):
  subject = mkSubject(header, isFwd=True)
  return createNewMessage(myemail, to, subject, messageText)


def createForwardWithAttachments(myemail, to, header, messageText, files):
  subject = mkSubject(header, isFwd=True)
  return createNewMessageWithAttachment(myemail, to, subject, messageText, files)


def createReplyWithAttachments(myemail, header, messageText, files):
  if header.replyTo:
    to = header.replyTo
  else:
    to = header.sender

  subject = mkSubject(header)

  if header.references:
    references = header.externalId + ' ' + header.references
  elif header.inReplyTo:
    references = header.externalId + ' ' + header.inReplyTo

  message = MIMEMultipart()
  message['From'] = getName(myemail) + ' <' + myemail + '>'
  message['To'] = to
  message['Subject'] = subject
  message['In-Reply-To'] = header.externalId
  message['References'] = references

  msg = MIMEText(messageText, _charset='utf-8')
  message.attach(msg)

  for file in files:
    content_type, encoding = mimetypes.guess_type(file)

    if content_type is None or encoding is not None:
      content_type = 'application/octet-stream'
    main_type, sub_type = content_type.split('/', 1)
    if main_type == 'text':
      with open(file, 'rb') as f:
        msg = MIMEText(f.read(), _subtype=sub_type)
    elif main_type == 'image':
      with open(file, 'rb') as f:
        msg = MIMEImage(f.read(), _subtype=sub_type)
    elif main_type == 'audio':
      with open(file, 'rb') as f:
        msg = MIMEAudio(f.read(), _subtype=sub_type)
    else:
      with open(file, 'rb') as f:
        msg = MIMEBase(main_type, sub_type)
        msg.set_payload(f.read())

    msg.add_header('Content-Disposition', 'attachment',
                   filename=os.path.basename(file))
    message.attach(msg)

  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}

'''


def createMessage(sender, messageText, **kwargs):
  '''
  Create a message.

  Args:
    sender: Email address of the sender.
    messageText: The text to appear in the body of the mail.

  Keyword args:
    type: One of NEW, REPLY, FORWARD.
    attachments: If present a list of files to attach.
    to: Who to send the mail to. 
    subject: Subject line of the mail. 
    header: If type is reply or foreward, this must be present.

  Returns: Base64-encoded email message.
  '''
  type = kwargs.get('type', 'NEW')
  attachments = kwargs.get('attachments', None)
  to = kwargs.get('to', None)
  subject = kwargs.get('subject', None)
  header = kwargs.get('header', None)

  if attachments:
    message = MIMEMultipart()
  else:
    message = MIMEText(messageText, _charset='utf-8')

  # if not to:
  #   if header.replyTo:
  #     to = header.replyTo
  #   else:
  #     to = header.sender

  # if type == 'REPLY':
  #     subject = mkSubject(header)
  # elif type == 'FORWARD':
  #     subject = mkSubject(header, isFwd=True)

  message['From'] = '{} <{}>'.format(getName(sender), sender)
  message['To'] = to
  message['Subject'] = subject

  if type == 'REPLY':
    if header.references:
      references = header.externalId + ' ' + header.references
    elif header.inReplyTo:
      references = header.externalId + ' ' + header.inReplyTo
    else:
      references = header.externalId
    message['In-Reply-To'] = header.externalId
    message['References'] = references
  if attachments:
    msg = MIMEText(messageText, _charset='utf-8')
    message.attach(msg)

    for file in attachments:
      content_type, encoding = mimetypes.guess_type(file)

      if content_type is None or encoding is not None:
        content_type = 'application/octet-stream'
      main_type, sub_type = content_type.split('/', 1)
      if main_type == 'text':
        with open(file, 'rb') as f:
          msg = MIMEText(f.read(), _subtype=sub_type)
      elif main_type == 'image':
        with open(file, 'rb') as f:
          msg = MIMEImage(f.read(), _subtype=sub_type)
      elif main_type == 'audio':
        with open(file, 'rb') as f:
          msg = MIMEAudio(f.read(), _subtype=sub_type)
      else:
        with open(file, 'rb') as f:
          msg = MIMEBase(main_type, sub_type)
          msg.set_payload(f.read())

      msg.add_header('Content-Disposition', 'attachment',
                     filename=os.path.basename(file))
      message.attach(msg)

  return {'raw': base64.urlsafe_b64encode(
      message.as_string().encode()).decode()}


def mkSubject(header, type):
  if type in ['REPLY','REPLYTOALL']:
    if (header.subject)[:3] not in ['re:', 'Re:']:
      subject = 'Re: ' + header.subject
    else:
      subject = header.subject
  elif type == 'FORWARD':
    subject = 'Fwd: ' + header.subject
  return subject

def mkTo(sender, header, type):
  if type == 'REPLY':
    to = header.sender
  elif type == 'REPLYTOALL':
    all = filter(lambda x: not re.search(sender,x), 
            (header.recipients).split(','))  
    to = header.sender
    for a in all:
        to += (', ' + a)
  return to

'''
def createReply(myemail, header, messageText):
  if header.replyTo:
    to = header.replyTo
  else:
    to = header.sender

  subject = mkSubject(header)

  if header.references:
    references = header.externalId + ' ' + header.references
  elif header.inReplyTo:
    references = header.externalId + ' ' + header.inReplyTo
  else:
    references = header.externalId 

  message = MIMEText(messageText, _charset='utf-8')
  message['From'] = getName(myemail) + ' <' + myemail + '>'
  message['To'] = to
  message['Subject'] = subject
  message['In-Reply-To'] = header.externalId
  message['References'] = references
  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}


def createNewMessage(myemail, to, subject, messageText):
  message = MIMEText(messageText, _charset='utf-8')
  message['To'] = to
  message['From'] = getName(myemail) + ' <' + myemail + '>'
  message['Subject'] = subject
  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}


def createNewMessageWithAttachment(myemail, to, subject, messageText, files):
  """Create a an email with attachments.

  Args:
    myemail: Email address of the sender.
    to: Email address of the receiver.
    subject: The subject of the email message.
    messageText: The text of the email message.
    files: List of files to attach. 

  Returns:
    An object containing a base64url encoded email object.
  """
  message = MIMEMultipart()
  message['To'] = to
  message['From'] = getName(myemail) + ' <' + myemail + '>'
  message['Subject'] = subject

  msg = MIMEText(messageText, _charset='utf-8')
  message.attach(msg)

  for file in files:
    content_type, encoding = mimetypes.guess_type(file)

    if content_type is None or encoding is not None:
      content_type = 'application/octet-stream'
    main_type, sub_type = content_type.split('/', 1)
    if main_type == 'text':
      with open(file, 'rb') as f:
        msg = MIMEText(f.read(), _subtype=sub_type)
    elif main_type == 'image':
      with open(file, 'rb') as f:
        msg = MIMEImage(f.read(), _subtype=sub_type)
    elif main_type == 'audio':
      with open(file, 'rb') as f:
        msg = MIMEAudio(f.read(), _subtype=sub_type)
    else:
      with open(file, 'rb') as f:
        msg = MIMEBase(main_type, sub_type)
        msg.set_payload(f.read())

    msg.add_header('Content-Disposition', 'attachment',
                   filename=os.path.basename(file))
    message.attach(msg)

  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}
'''


"""
vim:foldmethod=marker foldmarker=--->,<---
"""
