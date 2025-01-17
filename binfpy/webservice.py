import urllib.request
import urllib.parse
import os
from time import sleep
import binfpy.stats as stats
from io import StringIO
import gzip
import ssl
import json

""" This module is collection of functions for accessing the EBI REST web services,
    including sequence retrieval, searching, gene ontology, BLAST and ClustalW.
    The class EBI takes precautions taken as to not send too many requests when
    performing BLAST and ClustalW queries.

    See
    http://www.ebi.ac.uk/Tools/webservices/tutorials
    """

__ebiUrl__ = "http://www.ebi.ac.uk/Tools/"
__ebiGOUrl__ = "https://www.ebi.ac.uk/QuickGO/services/"
__uniprotUrl__ = "http://rest.uniprot.org/"
__ebiSearchUrl__ = "http://www.ebi.ac.uk/ebisearch/"


def fetch(entryId, dbName="uniprotkb", format="fasta"):
    """
    Retrieve a single entry from a database
    entryId: ID for entry e.g. 'P63166' or 'SUMO1_MOUSE' (database dependent; examples for uniprotkb)
    dbName: name of database e.g. 'uniprotkb' or 'pdb' or 'refseqn'; see http://www.ebi.ac.uk/Tools/dbfetch/dbfetch/dbfetch.databases for available databases
    format: file format specific to database e.g. 'fasta' or 'uniprot' for uniprotkb (see http://www.ebi.ac.uk/Tools/dbfetch/dbfetch/dbfetch.databases)
    See http://www.ebi.ac.uk/Tools/dbfetch/syntax.jsp for more info re URL syntax

    http://www.ebi.ac.uk/Tools/dbfetch/dbfetch?db=uniprotkb&id=P63166&format=fasta&style=raw&Retrieve=Retrieve
    """
    # Construct URL
    url = (
        __ebiUrl__
        + "dbfetch/dbfetch?style=raw&Retrieve=Retrieve&db="
        + dbName
        + "&format="
        + format
        + "&id="
        + entryId
    )
    # Get the entry
    try:
        data = urllib.request.urlopen(url).read().decode("utf-8")
        if data.startswith("ERROR"):
            raise RuntimeError(data)
        return data
    except urllib.error.HTTPError as ex:
        raise RuntimeError(ex.read())


def search(query, dbName="uniprot", format="list", limit=100, columns=""):
    """
    Retrieve multiple entries matching query from a database currently only via UniProtKB
    query: search term(s) e.g. 'organism:9606+AND+antigen'
    dbName: name of database e.g. 'uniprot', "refseq:protein", "refseq:pubmed"
    format: file format e.g. 'list', 'fasta' or 'txt'
    limit: max number of results (specify None for all results)
    See http://www.uniprot.org/faq/28 for more info re UniprotKB's URL syntax
    See http://www.ncbi.nlm.nih.gov/books/NBK25499/ for more on NCBI's E-utils
    """
    if dbName.startswith("uniprot"):
        # Construct URL
        if limit == None:  # no limit to number of results returned
            url = "{}{}/search?&format={}&query={}&columns={}".format(
                __uniprotUrl__, dbName, format, urllib.parse.quote(query), columns
            )
        else:
            url = "{}{}/search?format={}&limit={}&query={}&columns={}".format(
                __uniprotUrl__,
                dbName,
                format,
                str(limit),
                urllib.parse.quote(query),
                columns,
            )

        # Get the entries

        try:
            data = urllib.request.urlopen(url).read().decode("utf-8")
            if format == "list":
                return data.splitlines()
            else:
                return data
        except urllib.error.HTTPError as ex:
            raise RuntimeError(ex.read().decode("utf-8"))
    elif dbName.startswith("refseq"):
        dbs = dbName.split(":")
        if len(dbs) > 1:
            dbName = dbs[1]

        base = "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

        url = (
            base + "esearch.fcgi?db={}&term={}+AND+srcdb_refseq["
            "prop]&retmax={}".format(dbName, urllib.parse.quote(query), str(limit))
        )

        print(url)

        # Get the entries
        try:
            data = urllib.request.urlopen(url).read().decode("utf-8")
            words = data.split("</Id>")
            words = [w[w.find("<Id>") + 4 :] for w in words[:-1]]
            if format == "list":
                return words
            elif format == "fasta" and len(words) > 0:
                url = base + "efetch.fcgi?db=" + dbName + "&rettype=fasta&id="
                for w in words:
                    url += w + ","
                data = urllib.request.urlopen(url).read().decode("utf-8")
                return data
            else:
                return ""
        except urllib.error.HTTPError as ex:
            raise RuntimeError(ex.read())
    return


authorised_database_tag = {
    9606: ["Homo sapiens", "ACC", "ID"],
    3702: ["Arabidopsis thaliana", "TAIR_ID"],
    4932: ["Saccharomyces cerevisiae", "SGD_ID", "CYGD_ID"],
    10090: ["Mus musculus", "MGI_ID"],
}

"""
Gene Ontology service (QuickGO)
http://www.ebi.ac.uk/QuickGO/WebServices.html
Note that this service can be slow for queries involving a large number of entries.
"""


def getGOReport(positives, background=None):
    """Generate a complete GO term report for a set of genes (positives).
    Each GO term is also assigned an enrichment p-value (on basis of background, if provided).
    Returns a list of tuples (GO_Term_ID[str], Foreground_no[int], Term_description[str]) with no background, OR
    (GO_Term_ID[str], E-value[float], Foreground_no[int], Background_no[int], Term_description[str]).
    E-value is a Bonferroni-corrected p-value.
    """
    pos = set(positives)
    fg_map = getGOTerms(pos)
    fg_list = []
    for id in fg_map:
        for t in fg_map[id]:
            fg_list.append(t)
    bg_map = {}
    bg_list = []
    neg = set()
    if background != None:
        neg = set(background).difference(pos)
        bg_map = getGOTerms(neg)
        for id in bg_map:
            for t in bg_map[id]:
                bg_list.append(t)
    term_set = set(fg_list)
    term_cnt = {}

    nPos = len(pos)
    nNeg = len(neg)
    if background == None:
        for t in term_set:
            term_cnt[t] = fg_list.count(t)
        sorted_cnt = sorted(list(term_cnt.items()), key=lambda v: v[1], reverse=True)
    else:  # a background is provided
        for t in term_set:
            fg_hit = fg_list.count(t)
            bg_hit = bg_list.count(t)
            fg_nohit = nPos - fg_hit
            bg_nohit = nNeg - bg_hit
            term_cnt[t] = (
                fg_hit,
                fg_hit + bg_hit,
                stats.getFETpval(fg_hit, bg_hit, fg_nohit, bg_nohit, False),
            )
        sorted_cnt = sorted(
            list(term_cnt.items()), key=lambda v: v[1][2], reverse=False
        )

    ret = []
    for t in sorted_cnt:
        defin = getGODef(t[0])
        if background != None:
            ret.append(
                (
                    t[0],
                    t[1][2] * len(term_set),
                    t[1][0],
                    t[1][0] + t[1][1],
                    defin["name"],
                )
            )
        else:
            ret.append((t[0], t[1], defin["name"]))
    return ret


def getGODef(goterm):
    """
    Retrieve information about a GO term
    goterm: the identifier, e.g. 'GO:0002080'
    """
    # to turn off server certificate verification
    # if (not os.environ.__getitem__('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
    #    ssl._create_default_https_context = ssl._create_unverified_context
    # The better solution is to install network security certificates from the command line (MacOS below),
    # which should render the above unnecessary:
    # bash /Applications/Python*/Install\ Certificates.command

    # Construct URL with query term
    url = __ebiGOUrl__ + "ontology/go/search?query=" + goterm
    # Get the entry: fill in the fields specified below
    try:
        entry = {"id": None, "name": None, "aspect": None}
        data = urllib.request.urlopen(url).read().decode("utf-8")
        ret = json.loads(data)

        for row in ret["results"]:
            if row["id"] == goterm:
                for key in entry:
                    try:
                        entry[key] = row[key]
                    except:
                        entry[key] = None
                entry["def"] = row["definition"]["text"]
        return entry
    except urllib.error.HTTPError as ex:
        raise RuntimeError(ex.read())


def getGOTerms(genes):
    """
    Retrieve all GO terms for a given set of genes (or single gene).
    The result is given as a map (key=gene name, value=list of unique terms).
    """
    if type(genes) != list and type(genes) != set and type(genes) != tuple:
        genes = [genes]
    map = dict()
    batchsize = 100  # size of query batch
    genecnt = 0
    limitpage = 100  # number of record on each returned page
    while genecnt < len(genes):
        genebatch = []
        for index in range(batchsize):
            if genecnt < len(genes):
                genebatch.append(genes[genecnt])
            else:
                break
            genecnt += 1
        uri_string = "annotation/search?limit=" + str(limitpage) + "&geneProductId="
        for i in range(len(genebatch)):
            gene = genebatch[i]
            uri_string += gene + "," if i < len(genebatch) - 1 else gene
        # Construct URL
        # Get the entry: fill in the fields specified below
        # installing Python doesn't always install security certificates, and the below code is a workaround...
        # first turn off server certificate verification
        # if (not os.environ.__getitem__('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
        #    ssl._create_default_https_context = ssl._create_unverified_context
        # The better solution is to install network security certificates from the command line (MacOS below),
        # which should render the above unnecessary:
        # bash /Applications/Python*/Install\ Certificates.command
        page = 1
        try:
            while True:
                url = __ebiGOUrl__ + uri_string + "&page=" + str(page)
                urlreq = urllib.request.Request(url)
                urlreq.add_header("Accept-encoding", "gzip")
                response = urllib.request.urlopen(urlreq)
                if response.info().__getitem__("Content-Encoding") == "gzip":
                    buf = StringIO(response.read())
                    f = gzip.GzipFile(fileobj=buf)
                    data = f.read().decode("utf-8")
                else:
                    data = response.read().decode("utf-8")
                ret = json.loads(data)
                if page == 1 and int(ret["numberOfHits"]) > limitpage * 100:
                    print(
                        "Warning:",
                        ret["numberOfHits"],
                        "matches in a query. Be patient.",
                    )
                for row in ret["results"]:
                    genename = row[
                        "geneProductId"
                    ]  # would look like "UniProtKB:A0A140VJQ9"
                    gotermid = row["goId"]  # would look like "GO:0002080"
                    if not genename in map:
                        map[genename] = set([gotermid])
                    else:
                        map[genename].add(gotermid)
                if len(ret["results"]) < limitpage:
                    break
                page += 1
        except urllib.error.HTTPError as ex:
            raise RuntimeError(ex.read())
    return map


def getGenes(goterms, taxo=None):
    """
    Retrieve all genes/proteins for a given set of GO terms (or single GO term).
    Genes that are annotated with a more specific GO term than those given are included.
    taxo: use specific taxonomic identifier, e.g. 9606 (human); default is all
    The result is given as a map (key=gene name, value=list of unique terms).
    """
    if type(goterms) != list and type(goterms) != set and type(goterms) != tuple:
        goterms = [goterms]
    map = dict()
    batchsize = 10  # size of query batch
    termcnt = 0
    limitpage = 100  # number of record on each returned page
    while termcnt < len(goterms):
        termbatch = []
        for index in range(batchsize):
            if termcnt < len(goterms):
                termbatch.append(goterms[termcnt])
            else:
                break
            termcnt += 1
        uri_string = (
            "annotation/search?limit="
            + str(limitpage)
            + "&taxonId="
            + str(taxo)
            + "&goId="
            if taxo
            else "annotation/search?goId="
        )
        for i in range(len(termbatch)):
            term = termbatch[i]
            uri_string += term + "," if i < len(termbatch) - 1 else term
        # installing Python doesn't always install security certificates, and the below code is a workaround...
        # first turn off server certificate verification
        # if (not os.environ.__getitem__('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
        #    ssl._create_default_https_context = ssl._create_unverified_context
        # The better solution is to install network security certificates from the command line (MacOS below),
        # which should render the above unnecessary:
        # bash /Applications/Python*/Install\ Certificates.command
        page = 1
        try:
            while True:
                url = __ebiGOUrl__ + uri_string + "&page=" + str(page)
                urlreq = urllib.request.Request(url)
                urlreq.add_header("Accept-encoding", "gzip")
                response = urllib.request.urlopen(urlreq)
                if response.info().__getitem__("Content-Encoding") == "gzip":
                    buf = StringIO(response.read())
                    f = gzip.GzipFile(fileobj=buf)
                    data = f.read().decode("utf-8")
                else:
                    data = response.read().decode("utf-8")
                ret = json.loads(data)
                if page == 1 and int(ret["numberOfHits"]) > limitpage * 100:
                    print(
                        "Warning:",
                        ret["numberOfHits"],
                        "matches in a query. Be patient.",
                    )
                for row in ret["results"]:
                    genename = row[
                        "geneProductId"
                    ]  # would look like "UniProtKB:A0A140VJQ9"
                    gotermid = row["goId"]  # would look like "GO:0002080"
                    if not gotermid in map:
                        map[gotermid] = set([genename])
                    else:
                        map[gotermid].add(genename)
                if len(ret["results"]) < limitpage:
                    break
                page += 1
        except urllib.error.HTTPError as ex:
            raise RuntimeError(ex.read())
    return map


class EBI(object):
    __email__ = "anon@uq.edu.au"  # to whom emails about jobs should go
    __ebiServiceUrl__ = (
        "http://www.ebi.ac.uk/Tools/services/rest/"  # Use UQ mirror when available
    )
    __checkInterval__ = 2  # how long to wait between checking job status

    def __init__(self, service=None):
        """Initialise service session.
        service: presently, ncbiblast and clustalw2 are supported. Use None (default) for fetch/idmap jobs.
        """
        self.service = service
        self.lockFile = "%s.lock" % service

    def createLock(self):
        """Create a lock file to prevent submission of more than 1 job
        at a time by a single user."""
        fh = open(self.lockFile, "w")
        fh.write(self.jobId)
        fh.close()

    def removeLock(self):
        """Remove the lock file."""
        os.remove(self.lockFile)

    def isLocked(self):
        """Check if there is a lock on this service. If there is, check if
        the job is complete, and if so remove the lock. Return True if still
        locked and False if not."""
        if os.path.exists(self.lockFile):
            fh = open(self.lockFile, "r")
            jobId = fh.read()
            fh.close()
            status = self.status(jobId)
            if status == "RUNNING":
                self.jobId = jobId
                return True
            else:
                self.removeLock()
                return False
        else:
            return False

    """
    BLAST and CLUSTALW services
    """

    def run(self, params):
        """Submit a job to the given service with the given parameters, given
        as a dictionary. Return the jobId."""
        if self.service == None:
            raise RuntimeError("No service specified")
        if self.isLocked():
            raise RuntimeError(
                """You currently have a %s job running. You must
                                  wait until it is complete before submitting another job. Go to
                                  %sstatus/%s to check the status of the job."""
                % (self.service, self.__ebiServiceUrl__, self.jobId)
            )
        url = self.__ebiServiceUrl__ + self.service + "/run/"
        # ncbiblast database parameter needs special handling
        if self.service == "ncbiblast":
            databaseList = params["database"]
            del params["database"]
            databaseData = ""
            for db in databaseList:
                databaseData += "&database=" + db
            encodedParams = urllib.parse.urlencode(params).encode("utf-8")
            encodedParams += databaseData.encode("utf-8")
        else:
            encodedParams = urllib.parse.urlencode(params).encode("utf-8")
        print(url)
        self.jobId = urllib.request.urlopen(url, encodedParams).read().decode("utf-8")
        self.createLock()
        return self.jobId

    def status(self, jobId=None):
        """Check the status of the given job (or the current job if none is
        specified), and return the result."""
        if jobId is None:
            jobId = self.jobId
        url = self.__ebiServiceUrl__ + self.service + "/status/%s" % jobId
        status = urllib.request.urlopen(url).read().decode("utf-8")
        return status

    def resultTypes(self):
        """Get the available result types. Will only work on a finished job."""
        url = self.__ebiServiceUrl__ + self.service + "/resulttypes/%s" % self.jobId
        resultTypes = urllib.request.urlopen(url).read().decode("utf-8")
        return resultTypes

    def result(self, resultType):
        """Get the result of the given job of the specified type."""
        url = (
            self.__ebiServiceUrl__
            + self.service
            + "/result/%s/%s" % (self.jobId, resultType)
        )
        try:
            result = urllib.request.urlopen(url).read().decode("utf-8")
            if resultType == "error":
                raise RuntimeError("An error occurred: %s" % result)
        except urllib.error.HTTPError:
            if resultType == "error":
                raise RuntimeError(
                    "An unknown error occurred while processing the job (check your input)"
                )
            else:
                self.result("error")
        return result

    def submit(self, params, resultTypes):
        """Submit a new job to the service with the given parameters.
        Return the output in the specified format."""
        params["email"] = self.__email__
        self.run(params)
        print(("Submitted new", self.service, "job, jobId:", self.jobId))
        print("Please be patient while the job is completed")
        status = "RUNNING"
        observe = 0
        while status == "RUNNING":
            observe = observe + 1
            status = self.status()
            sleep(self.__checkInterval__)
        if status != "FINISHED":
            raise RuntimeError("An error occurred and the job could not be completed")
        print("Job complete.")
        self.removeLock()
        if type(resultTypes) != list:
            resultTypes = [resultTypes]
        results = []
        for resultType in resultTypes:
            results.append(self.result(resultType))
        if len(results) == 1:
            return results[0]
        else:
            return results


def getUniProtDict(ids, cols="", db="uniprot", identities=None):
    """

    :param ids: The list of UniProt IDs
    :param cols: The list of UniProt database columns
    :param db: The database to search - uniprot or uniref
    :param identity: The identity to search uniref with
    :return: A dictionary mapping each UniProt ID to another dictionary where the keys are database columns and the
    values are the information stored within those columns
    """

    """
    *** EXAMPLE USAGE ***
    Get a list of UniProt IDs and a list of UniProt columns you're interested in.
    Full list of UniProt column names - https://www.uniprot.org/help/uniprotkb_column_names

    uniprot_names = ['Q9LIR4', 'Q1JUQ1', 'P05791', 'P0ADF6']
    cols = ["lineage(SUPERKINGDOM)", "genes", "lineage(KINGDOM)"]    
    up_dict = getUniProtDict(uniprot_names, cols)

    for record in up_dict:
        print (record, up_dict[record].get("lineage(SUPERKINGDOM)"))

    print()

    for record in up_dict:
        print (record, up_dict[record].get("genes"))


    If a record doesn't have an entry in UniProt for that column it'll just return None

    print (up_dict['Q1JUQ1'])
    print (up_dict['Q1JUQ1']['lineage(KINGDOM)'])


    *** EXAMPLE USAGE FOR UNIREF SEARCHING ***

    up_dict = getUniProtDict(["Q9LIR4", "P99999"], cols=["members"], db="uniref", identities = 1.0)

    You can either pass a list of identities for each UniProt identifier (in which case the list of identities must be
    the same size as the list of identifiers. Or you can just pass a single identity to search Uniref at.
    """

    # Format the lists of IDs and columns correctly
    cols = ",".join(cols)

    if db == "uniprot":
        updated_ids = " or ".join(ids)

    elif db == "uniref":

        # If we just got a single value for an identity, create a list the same size as the queries with just this value
        if type(identities) != list:
            identities = [identities] * len(ids)
        elif len(identities) != len(ids):
            raise RuntimeError(
                "Either supply a single identity threshold or supply one for each identifier in the list"
            )

        # Check that the identity thresholds are valid values
        for x in identities:
            if x not in [1.0, 0.9, 0.5]:
                raise RuntimeError(
                    "UniRef threshold values must be either 1.0, 0.9, or 0.5. Supplied value was - "
                    + str(x)
                )

        # Add the query syntax around the identifiers
        updated_ids = ""
        for query, identity in zip(ids, identities):
            updated_ids += (
                "(member:" + query + "+AND+identity:" + str(identity) + ")+OR+"
            )

        updated_ids = updated_ids[0:-4]

    else:
        raise RuntimeError("Database should be either uniprot or uniref")

    url = "https://www.uniprot.org/" + db + "/"

    params = {"format": "tab", "query": updated_ids, "columns": "id," + cols}

    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data)
    opener = urllib.request.build_opener()
    response = opener.open(request)
    page = response.read(2000000000).decode("utf-8")
    up_dict = {}

    # For each record we retrieve, split the line by tabs and build up the UniProt dict
    for line in page.split("\n")[1:]:
        if line:
            splitlines = line.split("\t")
            id_dict = {}
            pos = 1
            for col in cols.split(","):
                id_dict[col] = None if splitlines[pos] == "" else splitlines[pos]
                pos += 1
            up_dict[splitlines[0]] = id_dict

    return up_dict
