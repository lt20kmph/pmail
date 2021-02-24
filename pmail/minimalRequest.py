import os
import sys
import pickle
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.modify',
          'https://www.googleapis.com/auth/gmail.settings.basic']


class MemoryCache(Cache):
  '''
  This is needed so that the cache is working inside Thread
  objects.
  '''
  _CACHE = {}

  def get(self, url):
    return MemoryCache._CACHE.get(url)

  def set(self, url, content):
    MemoryCache._CACHE[url] = content


def test(path):
  """Shows basic usage of the Gmail API.
  Lists the user's Gmail labels.
  """
  creds = None
  # The file token.pickle stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists('token.pickle'):
    with open('token.pickle', 'rb') as token:
      creds = pickle.load(token)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open('token.pickle', 'wb') as token:
      pickle.dump(creds, token)

  service = build('gmail', 'v1', credentials=creds, cache=MemoryCache())

  # Call the Gmail API
  results = service.users().labels().list(userId='me').execute()
  labels = results.get('labels', [])

  if not labels:
    print('No labels found.')
  else:
    print('Labels:')
    for label in labels:
      print(label['name'])

  currentFilters = service.users().settings().filters()\
      .list(userId='me').execute()

  if not currentFilters:
    print('No filters found.')
  else:
    print('Filters:')
    for f in currentFilters['filter']:
      print(f)


if __name__ == '__main__':
  path = sys.argv[1]
  test(path)
