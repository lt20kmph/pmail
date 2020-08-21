#!/usr/bin/python

# ---> Imports
import re
import base64
import mimetypes
import os

from apiclient import errors
from pmail.common import logger, config
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
# <---

# ---> Send a message


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
    message = (service.users().messages().
               send(userId=userId, body=message).execute())
    # print('Message Id: %s' % message['id'])
    return message
  except errors.Error as e:
    logger.warning(e)

# <---

# ---> Create a message


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
    cc: Carbon copies sent here.
    bcc: Blind carbon copies.
    subject: Subject line of the mail. 
    header: If type is reply or foreward, this must be present.

  Returns: Base64-encoded email message.
  '''
  type = kwargs.get('type', 'NEW')
  attachments = kwargs.get('attachments', None)
  to = kwargs.get('to', None)
  cc = kwargs.get('cc', None)
  bcc = kwargs.get('bcc', None)
  subject = kwargs.get('subject', None)
  header = kwargs.get('messageInfo', None)

  if attachments:
    message = MIMEMultipart()
  else:
    message = MIMEText(messageText, _charset='utf-8')

  message['From'] = '{} <{}>'.format(config.getName(sender), sender)
  message['To'] = to
  if cc:
    message['Cc'] = cc
  if bcc:
    message['Bcc'] = bcc
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
  '''
  If sending a reply or forward then make the subject.

  Args:
    header: The MessageInfo object of the message being replied 
    or forewarded.
    type: One of REPLY, REPLY_TO_ALL, FORWARD.

  Returns:
    A string with the subject.
  '''
  if type in ['REPLY', 'REPLY_TO_ALL']:
    if (header.subject)[:3] not in ['re:', 'Re:']:
      subject = 'Re: ' + header.subject
    else:
      subject = header.subject
  elif type == 'FORWARD':
    subject = 'Fwd: ' + header.subject
  return subject


def mkTo(sender, header, type):
  '''
  If sending a reply figure out who to reply to.
  
  Args:
    sender: Whoever is sending mail.
    header: The MessageInfo object of the mail being replied to.
    type: One of REPLY or REPLY_TO_ALL.
  '''
  if type == 'REPLY':
    to = header.sender
  elif type == 'REPLY_TO_ALL':
    all = filter(lambda x: not re.search(sender, x),
                 (header.recipients).split(','))
    to = header.sender
    for a in all:
      to += (', ' + a)
  return to

# <---

"""
vim:foldmethod=marker foldmarker=--->,<---
"""
