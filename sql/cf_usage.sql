
select cf.id, cf.cfname, description, count(*) from customfield as cf
left join customfieldvalue as cfv on cfv.customfield = cf.id 
where cf.cfname NOT SIMILAR TO '%(Contour|Epic|Signoff)%' 
  and cf.cfname not in ('Rank','Bug ID','Date of First Response','Story Points','issueFunction','Release Version History','Code in branch')
  and cf.cfname not in ('Points','Units','Customer id','Customer_reported','DueTime',
'Hook1','MS Third Party','PercentDone','Port Fix Version/s','Release Note','Release Note Text','Reproducibility','Scrum Team','Teams')
group by cf.id, cf.cfname, description
having count(*) < 2

order by count(*), cf.id
;
