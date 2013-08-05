select reqcontent as jql from "searchrequest" Where reqcontent LIKE '%Resolution%' OR reqcontent LIKE '%Status%'
  UNION
select "QUERY" as jql from "AO_60DB71_QUICKFILTER" where "QUERY" LIKE '%Resolution%' OR "QUERY" LIKE '%Status%'
;
