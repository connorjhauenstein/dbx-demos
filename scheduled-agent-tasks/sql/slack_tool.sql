-- A governed Slack tool for agents: post a message as your Slack app's bot.
-- The bot token stays in a Unity Catalog connection; agents only see the post_slack_message function,
-- which Databricks managed MCP serves as a tool. List it in a task's task.yml under `functions:`.
--
-- Before running: store the bot token (xoxb-..., scopes chat:write and im:write) in a Databricks secret,
-- for example `databricks secrets put-secret slack bot_token`. Replace <catalog>.<schema> and <agents-sp>.
-- Safe to rerun: CREATE OR REPLACE FUNCTION drops the function's grants, so the grants below restore them.

CREATE CONNECTION IF NOT EXISTS slack_bot TYPE HTTP OPTIONS (
  host 'https://slack.com',
  port '443',
  base_path '/api',
  bearer_token secret('slack', 'bot_token')
);

CREATE OR REPLACE FUNCTION <catalog>.<schema>.post_slack_message(
  channel STRING COMMENT 'Slack channel ID (C...) or user ID (U...) to post to. A channel must have the bot invited.',
  text STRING COMMENT 'Message text in Slack mrkdwn. With blocks, this is the notification preview.',
  blocks STRING DEFAULT NULL COMMENT 'Optional Slack Block Kit layout: a JSON array of blocks, as a string.'
)
RETURNS STRING
COMMENT 'Post a message to Slack as the team bot. Returns ok, or the Slack error (for example invalid_blocks).'
RETURN (
  SELECT CASE WHEN get_json_object(r.text, '$.ok') = 'true' THEN 'ok' ELSE coalesce(get_json_object(r.text, '$.error'), r.text) END
  FROM (SELECT http_request(
    conn => 'slack_bot',
    method => 'POST',
    path => '/chat.postMessage',
    json => CASE WHEN blocks IS NULL THEN to_json(named_struct('channel', channel, 'text', text))
                 ELSE to_json(named_struct('channel', channel, 'text', text, 'blocks', parse_json(blocks))) END
  ) AS r)
);

-- The function calls Slack with the caller's access to the connection, so the agents' service principal needs both.
GRANT EXECUTE ON FUNCTION <catalog>.<schema>.post_slack_message TO `<agents-sp>`;
GRANT USE CONNECTION ON CONNECTION slack_bot TO `<agents-sp>`;
