select top 100 user_name, directory_id from [jiraschema].[cwd_user] 
where directory_id NOT IN (10000,10100)
AND user_name NOT IN (SELECT user_name from [jiraschema].[cwd_user] where directory_id = 10000);
