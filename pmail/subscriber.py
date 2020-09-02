import os
from pmail.common import config, logger
from google.cloud import pubsub_v1
from queue import Queue
import json

def subscribe(pubSubQue,account):
  accountInfo = config.accounts[account]
  project_id = accountInfo['project_id']
  os.environ['GOOGLE_APPLICATION_CREDENTIALS'] =\
    accountInfo['pubsub_credentials']

  print(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
  subscriber = pubsub_v1.SubscriberClient()

  subscription_name = 'projects/{project_id}/subscriptions/{sub}'.format(
      project_id=project_id,
      sub='pmail-update',
  )

  # logger.info(subscription_name)

  def callback(message):
      # print(message.data)
      logger.info('Message from pubsub: {}'
                  .format(message.data.decode('utf-8')))
      pubSubQue.put(message.data)
      message.ack()

  future = subscriber.subscribe(subscription_name, callback)
  return future

if __name__ == '__main__':
  q = Queue()
  subscribe(q,'lostoli@gmail.com')

  m = q.get()
  m = m.decode('utf-8')
  m = json.loads(m)
  print(m['emailAddress'])
'''
try:
    future.result()
except KeyboardInterrupt:
    future.cancel()
'''
