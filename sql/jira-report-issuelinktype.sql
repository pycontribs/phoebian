select linktype, issuelinktype.linkname, count(*) from issuelink
join issuelinktype on issuelink.linktype = issuelinktype."id"
group by linktype, issuelinktype.linkname
;