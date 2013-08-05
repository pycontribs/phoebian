CREATE OR REPLACE FUNCTION jira_reporter_email_for_project(in TEXT) returns setof TEXT AS
$$
select 
DISTINCT cwd_user.email_address from jiraissue
  LEFT JOIN cwd_user on cwd_user.user_name = jiraissue.reporter
  where PKEY LIKE '$1-%' AND email_address IS NOT NULL
  order by email_address

$$
language sql;

select * from jira_reporter_email_for_project('XOP');
