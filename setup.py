#!/usr/bin/python

# ---> Imports

from common import mkService, getName, UserInfo, s, logger

# <---


def setSendAs(email, name):
  service = mkService()
  sendAsResource = {'sendAsEmail': email,
                    'replyToAddress': email,
                    'displayName': name}
  response = service.users().settings().sendAs().update(userId = 'me',
          sendAsEmail = email,
          body=sendAsResource).execute()
  return response

def listSendAs():
  service = mkService()
  response = service.users().settings().sendAs().list(userId = 'me'
          ).execute()
  return response


if __name__ == '__main__':
    emailAddress = (s.query(UserInfo)[0]).emailAddress
    logger.info('Attempting to set send as name: {} for {}'.format(
        getName(emailAddress),
        emailAddress
        ))
    print(setSendAs(emailAddress, getName(emailAddress)))
    print(listSendAs())
"""
vim:foldmethod=marker foldmarker=--->,<---
"""
