import os
from pmail.common import config, logger
from google.cloud import pubsub_v1


def subscribe(pubSubQue, account):
  '''
  Function which subscribes to a pubsub topic.

  Args:
    pubSubQue: ClearableQueue object, in which we should put any messages we
    recieve.
    account: which account we want to subscribe for.

  Returns:
    A google.cloud.pubsub_v1.subscriber.StreamingPullFuture object.
  '''
  accountInfo = config.accounts[account]
  project_id = accountInfo['project_id']
  os.environ['GOOGLE_APPLICATION_CREDENTIALS'] =\
      accountInfo['pubsub_credentials']

  subscriber = pubsub_v1.SubscriberClient()

  subscription_name = 'projects/{project_id}/subscriptions/{sub}'.format(
      project_id=project_id,
      sub='pmail-update',
  )

  # logger.info(subscription_name)

  def callback(message):
    logger.info('Message from pubsub: {}'
                .format(message.data.decode('utf-8')))
    pubSubQue.put(message.data)
    message.ack()

  future = subscriber.subscribe(subscription_name, callback)
  return future
