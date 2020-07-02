#!/usr/bin/python

"""Send an email message from the user's account.
"""

# ---> Imports
import base64
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
# from email.utils import make_msgid
import mimetypes
import os

from common import logger
from apiclient import errors
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
    message = (service.users().messages().send(userId=userId, body=message)
               .execute())
    # print('Message Id: %s' % message['id'])
    return message
  except errors.Error as e:
    logger.warning(e)


def createReply(myemail, header, messageText):
  if header.replyTo:
    to = header.replyTo
  else:
    to = header.sender

  if (header.subject)[:3] not in ['re:', 'Re:']:
    subject = 'Re: ' + header.subject
  else:
    subject = header.subject

  if header.references:
    references = header.externalId + ' ' + header.references
  elif header.inReplyTo:
    references = header.externalId + ' ' + header.inReplyTo

  message = MIMEText(messageText, _charset='utf-8')
  message['from'] = myemail
  message['to'] = to
  message['subject'] = subject
  message['in-reply-to'] = header.externalId
  message['references'] = references
  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}


def createNewMessage(myemail, to, subject, messageText):
  """Create a message for an email.

  Args:
    to: Email address of the receiver.
    subject: The subject of the email message.
    messageText: The text of the email message.

  Returns:
    An object containing a base64url encoded email object.
  """
  message = MIMEText(messageText, _charset='utf-8')
  message['to'] = to
  message['from'] = myemail
  message['subject'] = subject
  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}


def CreateMessageWithAttachment(sender, to, subject, message_text, file_dir,
                                filename):
  """Create a message for an email.

  Args:
    sender: Email address of the sender.
    to: Email address of the receiver.
    subject: The subject of the email message.
    message_text: The text of the email message.
    file_dir: The directory containing the file to be attached.
    filename: The name of the file to be attached.

  Returns:
    An object containing a base64url encoded email object.
  """
  message = MIMEMultipart()
  message['to'] = to
  message['from'] = sender
  message['subject'] = subject

  msg = MIMEText(message_text)
  message.attach(msg)

  path = os.path.join(file_dir, filename)
  content_type, encoding = mimetypes.guess_type(path)

  if content_type is None or encoding is not None:
    content_type = 'application/octet-stream'
  main_type, sub_type = content_type.split('/', 1)
  if main_type == 'text':
    fp = open(path, 'rb')
    msg = MIMEText(fp.read(), _subtype=sub_type)
    fp.close()
  elif main_type == 'image':
    fp = open(path, 'rb')
    msg = MIMEImage(fp.read(), _subtype=sub_type)
    fp.close()
  elif main_type == 'audio':
    fp = open(path, 'rb')
    msg = MIMEAudio(fp.read(), _subtype=sub_type)
    fp.close()
  else:
    fp = open(path, 'rb')
    msg = MIMEBase(main_type, sub_type)
    msg.set_payload(fp.read())
    fp.close()

  msg.add_header('Content-Disposition', 'attachment', filename=filename)
  message.attach(msg)

  return {'raw': base64.urlsafe_b64encode(message.as_string())}


"""
vim:foldmethod=marker foldmarker=--->,<---
"""
