/* Source this as and in mysql -u korp korp_auth. Except don't if
   korp_auth has valuable content already. By Jussi Piitulainen,
   jpiitula@ling.helsinki.fi, for FIN-CLARIN, Dec 2013. */

drop table if exists auth_academic;
drop table if exists auth_allow;
drop table if exists auth_secret;
drop table if exists auth_license;

/* HTTP Basic Authentication username -
   should rather be an EPPN */
create table auth_academic(person varchar(80) not null,
                           primary key (person));

/* CWB name */
/* PUB, ACA, RES */
create table auth_license(corpus varchar(80) not null,
			  license char(3) not null,
                          primary key (corpus));

/* Personal access to a corpus -
   needed for RES, can have for ACA (or even PUB ;)
   corpus must be known in this authorization service,
   person need not (might be REMOTE_USER of Shibboleth) */
create table auth_allow(person varchar(80) not null,
                        corpus varchar(80) not null,
                        primary key (person, corpus),
			constraint foreign key (corpus)
				   references auth_license(corpus));

/* In the clear! */
create table auth_secret(person varchar(80) not null,
       	     		 secret varchar(240) not null,
                         primary key (person));
