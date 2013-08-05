SELECT
    user_name
FROM
    cwd_user
WHERE
    user_name NOT IN (
        SELECT DISTINCT
            LASTMODIFIER
        FROM
            CONTENT
        WHERE
            LASTMODIFIER NOT LIKE NULL
    )
    AND user_name IN  (
select cwd_user.user_name as user_name from cwd_group  
JOIN cwd_membership on cwd_group.id = cwd_membership.parent_id
JOIN cwd_user on cwd_membership.child_user_id = cwd_user.id
where group_name = 'confluence-users'
order by user_name
)


ORDER BY
    user_name;