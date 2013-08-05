begin;
delete from cwd_membership where child_user_id IN (
select id  from cwd_user where user_name LIKE 'tstat%'
);
delete from cwd_user_attribute where user_id IN (
select id  from cwd_user where user_name LIKE 'tstat%'
);

delete from cwd_user where user_name LIKE 'tstat%';
end;
