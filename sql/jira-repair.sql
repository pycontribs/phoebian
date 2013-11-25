/*

    Fixes different JIRA database inconsistencies, which sadly are quite common on real life situation.

    This script will work only on PostgreSQL and is desiged to work with JIRA 5.x but it may also work with 6.x
*/

-- repair NULL mime types... usualy caused by REST file uploads

update fileattachment set mimetype = 'text/plain' where mimetype is null AND filename SIMILAR TO '%(.txt|.log)';
update fileattachment set mimetype = 'image/jpeg' where mimetype is null AND filename SIMILAR TO '%(.jpg)';
update fileattachment set mimetype = 'application/octet-stream' where mimetype is null AND filename SIMILAR TO '%(.dmp)';
update fileattachment set mimetype = 'application/x-bzip2' where mimetype is null AND filename SIMILAR TO '%(.bz2)';
update fileattachment set mimetype = 'application/x-compressed' where mimetype is null AND filename SIMILAR TO '%(.gz)';
update fileattachment set mimetype = 'application/x-bzip2' where mimetype is null AND filename SIMILAR TO '%(.bz2)';

-- if next line returns something it means that this script supports improvements.
select * from fileattachment where mimetype is null;
