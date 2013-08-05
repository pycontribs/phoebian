
USE jiradb;
GO
BACKUP DATABASE jiradb
TO DISK = 'c:\jiradata\jiradb.Bak'
   WITH FORMAT,
      MEDIANAME = 'Z_SQLServerBackups',
      NAME = 'Full Backup of jiradb';
GO
