# UI Version 1.0
# Created by: Carlos Martinez
# Purpose: Take in a list of DOIs and upload their metadata and PDFs (if possible) to DSpace.
#          Additionally, it stores performance metrics in a metrics database, new authors in
#          an authors database, every uploaded publication in a publication database, and a 
#          relation of both (author-publication) in a combined database.
# File is meant to be used by an additional file (UI)
# Metadata Format:
#   dc.title                    (Title)
#   dc.creator                  (Authors)
#   dc.date.issued              (Year)
#   dc.identifier.uri           (DOI)
#   dc.subject                  (Keywords)
#   dc.description              (License)
#   dc.description.abstract     (Abstract)
#   dc.language.iso             (Language)
#   dc.type                     (Type)
#   dc.identifier.citation      (Citation)
# APIs used: Scopus, Unpaywall, and DSpace

import os
import copy
import json
import MySQLdb
import datetime
import requests
from PyPDF2 import PdfWriter
from tkinter import filedialog
from create_cover_page_UI import create_cover_page


# *********** GLOBAL VARIABLES ***********
from keys_UI import (COLLECTION_URI, TTU_IDs, TTUHSC_IDs, TTUL_DSPACE_URL, DSPACE_HEADERS,
                    SCOPUS_SEARCH_API, SCOPUS_DETAILS_API, SCOPUS_HEADERS, 
                    UNPAYWALL_API, PDF_HEADERS,
                    SQLDB_HOST, SQLDB_USER, SQLDB_PW, SQL_DB, 
                    AUTHORS_DB, PUBLICATIONS_DB, COMBINED_DB, METRICS_DB)

EMAIL = ''          # Given by the user, used for DSpace and Unpaywall
DOIS_FOR_PDF = 6    # Number of characters to be used from DOIs for a PDF file

# Metrics DB
MDB_DOIS  = 0       # will be updated throughout the program
MDB_ITEMS = 0       # will be updated throughout the program
MDB_PDFS  = 0       # will be updated throughout the program
MDB_ERROR = 0       # will be updated throughout the program
MDB_DATE = datetime.datetime.now().strftime('%Y-%m-%d')
# Publications DB
PUB_DB_DICT = dict()

# Metadata columns
TITLE = "dc.title"
AUTHORS = "dc.creator" 
YEAR = "dc.date.issued"
DOI = "dc.identifier.uri"
KEYWORDS = "dc.subject"
LICENSE = "dc.description"
ABSTRACT = "dc.description.abstract"
LANGUAGE = "dc.language.iso"
TYPE = "dc.type"
CITATION = "dc.identifier.citation"


def connect_to_db():
    '''
    Purpose: Connect to our database and return the variables to make queries
    Input: N/A
    Output: Database variable (used to close the connection) and cursor (used to make queries)
    '''
    db = MySQLdb.connect(
            host=SQLDB_HOST,
            user=SQLDB_USER,
            passwd=SQLDB_PW,
            db=SQL_DB)
    cursor = db.cursor()
    return db, cursor


def login_dspace(email, dspace_pw):
    '''
    Purpose: Log in user to DSpace
    Input: N/A
    Output: No output but can only get out if user is authenticated
    '''
    global EMAIL
    data = {"email": email, "password": dspace_pw}
    res = requests.post(TTUL_DSPACE_URL+'login', data=data)
    if res.status_code == 200:
        EMAIL = email
        DSPACE_HEADERS['Cookie'] = f"JSESSIONID={res.cookies['JSESSIONID']}"
        return 1
    return 0


def ask_dois_file():
    '''
    Purpose: Ask the user to select a txt file
    Input: N/A
    Ouput: Read only txt (with DOIs) file object
    '''
    dois_file = filedialog.askopenfile(filetypes=[('Text File', '*.txt')])
    return dois_file


def read_dois(dois_file):
    '''
    Purpose: Function reads and returns all the DOIs in the file
    Input: DOIs file object
    Output: List with just DOIs
    '''
    num_dois = []
    for line in dois_file:
        doi = line.strip()
        if 'doi.org' in doi:
            split_doi = doi.split('/')
            for piece in split_doi:
                if '10.' in piece:
                    num_dois.append('/'.join(split_doi[split_doi.index(piece):]))
                    break
            #num_dois.append('/'.join(doi.split('/')[-2:]))
        else:
            num_dois.append(doi)
    return num_dois


def check_duplicates(ui, num_dois):
    '''
    Purpose: Verify that we're not adding duplicates to our system
    Input: A list of DOIs given by the user
    Output: An updated list with valid DOIs (if none, program finishes)
    '''
    global MDB_DOIS
    DSPACE_HEADERS['Content-Type'] = 'application/json'
    url = TTUL_DSPACE_URL+'/items/find-by-metadata-field?expand=parentCollection'
    new_dois = copy.deepcopy(num_dois)
    ui.print_to_ui("Checking for duplicates on DSpace")
    for doi in new_dois:
        
        data = json.dumps({"key": "dc.identifier.uri", "value": f'https://doi.org/{doi}'})
        res = requests.post(url, data=data, headers=DSPACE_HEADERS)
        if res.status_code == 200 and len(res.json())>0:
            for item in res.json():
                if item["parentCollection"]["uuid"] == COLLECTION_URI:
                    ui.print_to_ui(f"***{doi} already in the system***")
                    num_dois.remove(doi)
                    break
    MDB_DOIS = len(num_dois)
    ui.print_to_ui(f"\nNumber of valid DOIs identified: {len(num_dois)}\n")


def create_metadata_list(ui, num_dois):
    '''
    Purpose: Create a list of lists with the metadata for the papers while calling the necessary APIs
    Input: Num DOIs (10.1073/pnas.2215372119)
    Output: Metadata list of lists
    '''
    global MDB_ERROR, MDB_DOIS
    MDB_DOIS = len(num_dois)
    all_metadata = []
    not_analyzed = []
    for doi in num_dois:
        res = requests.get(SCOPUS_SEARCH_API+f'({doi})', headers=SCOPUS_HEADERS).json()
        try:
            scopus_id = res['search-results']['entry'][0]['dc:identifier'].split(':')[-1]
        except KeyError:
            not_analyzed.append(doi)
            ui.print_to_ui (f"***Couldn't find {doi} on Scopus API***")
            continue
        
        res = requests.get(SCOPUS_DETAILS_API+scopus_id, headers=SCOPUS_HEADERS).json()["abstracts-retrieval-response"]
        try:
            PUB_DB_DICT[doi] = dict()
            paper_metadata = store_paper_metadata(res, doi)
        except Exception as e:
            MDB_ERROR = 1
            ui.print_to_ui (f"***Couldn't store metadata for {doi}***")
            ui.print_to_ui (e)
            continue
        
        all_metadata.append(paper_metadata)
        del paper_metadata
    for doi in not_analyzed:
        num_dois.remove(doi)
    ui.print_to_ui (f"\nExtracted metadata of {len(num_dois)} DOIs\n")
    return all_metadata


def store_paper_metadata(res, doi):
    '''
    Purpose: Store paper's metadata in a list + store paper's info in dictionary for DB use
    Input: API response (all of paper's metadata)
    Output: Paper's metadata in a list
    '''
    paper_metadata = []
    # Title
    paper_metadata.append(res['coredata']['dc:title'])
    # Authors
    paper_metadata.append(store_paper_authors(doi, res['authors']['author']))
    # Year
    paper_metadata.append(res['item']['bibrecord']['head']['source']['publicationdate']['year'])
    # DOI
    paper_metadata.append('https://doi.org/'+doi)
    # Keywords
    paper_metadata.append(store_paper_keywords(res['item']['bibrecord']['head']['citation-info']))
    # License and Abstract
    store_paper_license_and_abstract(res, paper_metadata, doi)
    # Language
    paper_metadata.append(res['item']['bibrecord']['head']['citation-info']['citation-language']['@xml:lang'])
    # Type
    paper_metadata.append(res['coredata']['subtypeDescription'])
    # Citation
    paper_metadata.append(create_apa_citation(paper_metadata, res['authors']['author'], res['coredata']))
    # DB
    PUB_DB_DICT[doi]['Title'] = paper_metadata[0]
    PUB_DB_DICT[doi]['Year'] = paper_metadata[2]
    PUB_DB_DICT[doi]['Date Available'] = MDB_DATE
    return paper_metadata


def store_paper_authors(doi, res_authors):
    '''
    Purpose: Create a list of authors and identify TTU authors
    Input: DOI + List of authors of a given paper -- Scopus response
    Ouput: List of authors with a '(TTU)' tag for TTU authors 
            + calls function to store TTU authors in DB
            + stores scopusID of TTU authors in a list for PUB_DB_DICT
    '''
    authors_list = []
    authors_db = []
    authors_id = []
    for author in res_authors:
        ttu = 0
        hsc = 0
        if 'ce:given-name' in author['preferred-name']:
            first_name =  author['preferred-name']['ce:given-name']
        else: first_name = author['ce:initials']
        last_name = author['preferred-name']['ce:surname']
        full_name = last_name + ', ' + first_name
        # Get affiliation
        try:
            if author['affiliation']['@id'] in TTU_IDs:
                full_name += ' (TTU)'
                ttu = 1
            elif author['affiliation']['@id'] in TTUHSC_IDs:
                full_name += ' (TTUHSC)'
                ttu = 1
                hsc = 1
        except TypeError:
            for affiliation in author['affiliation']:
                if affiliation['@id'] in TTU_IDs:
                    full_name += ' (TTU)'
                    ttu = 1
                    break
                elif affiliation['@id'] in TTUHSC_IDs:
                    full_name += ' (TTUHSC)'
                    ttu = 1
                    hsc = 1
                    break
        except KeyError:
            # Author has no affiliations
            pass
        authors_list.append(full_name)
        if ttu:
            scopusid = author['@auid']
            authors_id.append(scopusid)
            last_emailed = (datetime.datetime.now()-datetime.timedelta(days=365)).strftime('%Y-%m-%d')
            authors_db.append([scopusid, first_name, last_name, last_emailed, hsc])
    store_authors_in_db(authors_db)
    PUB_DB_DICT[doi]['Authors'] = authors_id
    return authors_list


def store_authors_in_db(authors):
    '''
    Purpose: Check if each TTU author of a given paper is already stored in our DB
                if not, we need to save all the information required 
    Input: Data of every TTU authors in a paper
    Output: Updated DB if we don't have authors' data
    '''
    if len(authors) == 0:
        return
    db, cursor = connect_to_db()
    for author in authors:
        # Each author in here is Faculty
        if cursor.execute(f'SELECT 1 FROM {AUTHORS_DB} WHERE scopus_id = "{author[0]}"') == 0:
            # Author is not currently stored in our DB
            # so we need to store author's data
            # New authors start with 0 papers, no email, no parent/related to, and default to faculty
            cursor.execute(f"INSERT INTO faculty_research_author_test \
                        (first_name, last_name, last_emailed, hsc, scopus_id, num_papers, email, related_to, faculty) \
                        VALUES ('{author[1]}', '{author[2]}', '{author[3]}', {author[4]}, '{author[0]}', 0, '', NULL, 1)")
    db.commit()
    db.close()


def store_paper_keywords(res):
    '''
    Purpose: Create a list of a paper keywords
    Input: Scopus response
    Ouput: Either a list of keywords found on the APIs response or None
    '''
    try:
        keywords = [x['$'] for x in res['author-keywords']['author-keyword']]
    except KeyError:
        keywords = None
    return keywords


def store_paper_license_and_abstract(res, metadata, doi):
    '''
    Purpose: Store the paper's license and abstract
    Input: Scopus response, paper's metadata list, paper's DOI
    Ouput: N/A (Updated metadata list)
    '''
    
    lic = res['coredata']['publishercopyright'] if 'publishercopyright' in res['coredata'] else ''
    if type(lic) == list:
        lic = lic[0]['$']
    abstract = res['item']['bibrecord']['head']['abstracts'].replace(lic, '') if res['item']['bibrecord']['head']['abstracts'] != None else ''
    try:
        cc_type = requests.get(UNPAYWALL_API+f'{doi}?email={EMAIL}').json()["best_oa_location"]["license"]
    except TypeError:
        cc_type = ''
    lic += f' {cc_type}'
    metadata.append(lic)
    metadata.append(abstract)


def create_apa_citation(metadata, res_authors, res_journal):
    '''
    Purpose: Create an APA 7th edition for a paper
    Input: Paper's metadata list
    Ouput: APA citation following 7th edition standards

    Standards APA 7th ed:
        Author or authors. The surname is followed by first initials.
        Year of publication of the article (in round brackets).
        Article title.
        Journal title (in italics).
        Volume of journal (in italics).
        Issue number of journal in round brackets (no italics).
        Page range of article.
        DOI or URL
    '''
    citation = ''
    citation += get_author_citation(metadata, res_authors)
    citation += metadata[2] + '. '
    citation += metadata[0] + '. '
    citation += get_journal_info(res_journal)
    citation += metadata[3]
    return citation


def get_author_citation(metadata, res_authors):
    '''
    Purpose: Create a string with author(s) for paper's citation
    Input: Previously stored metadata and Scopus API response -- author specific 
    Output: String with author(s) for paper's citation
    '''
    if len(metadata[1]) < 2:
        authors_name = res_authors[0]["ce:indexed-name"].replace(' ', ', ') + '. '
    else:
        authors_name = ''
        i = 1
        for author in res_authors:
            if len(metadata[1])>19 and i==20:
                authors_name += '. . . ' + res_authors[-1]["ce:indexed-name"].replace(' ', ', ')+'. '
                break
            elif i==len(metadata[1]):
                authors_name += '& ' + author["ce:indexed-name"].replace(' ', ', ')+'. '
            else:
                authors_name += author["ce:indexed-name"].replace(' ', ', ')+', '
            i += 1
    return authors_name


def get_journal_info(res_journal):
    '''
    Purpose: Join different pieces of journal info to add to the citation
    Input: Scopus API response -- journal specific
    Output: A string that identifies the paper's journal information
    '''
    journal = res_journal['prism:publicationName']
    # Being safe if API doesn't have volume num
    try:
        volume = res_journal['prism:volume']
    except:
        volume = None
    # Being safe if API doesn't have issue num
    try:
        issue = res_journal['prism:issueIdentifier']
    except:
        issue = None

    if volume == None:
        # We make the assumption that if volume is not there, issue is not either
        journal += '. '
    elif issue == None:
        # Volume is not None
        journal += ', ' + volume + '. '
    else: 
        journal += f', {volume}({issue}). '
    return journal


def download_pdfs_from_doi(ui, dois):
    '''
    Purpose: For each DOI given to the program, download their PDF (if available)
    Input: List of DOIs
    Output: Dictionary with the DOIs that we had PDFs (each DOI is a key with null value -- will be updated later)
    '''
    downloaded = 0
    dois_pdf_dict = dict()
    dois_cp_dict = dict()
    for doi in dois:
        
        try:
            title = requests.get(UNPAYWALL_API+f'{doi}?email={EMAIL}').json()["title"]
            pdf_url = requests.get(UNPAYWALL_API+f'{doi}?email={EMAIL}').json()["best_oa_location"]['url_for_pdf']
        except TypeError:
            if title:
                ui.print_to_ui (f"***Couldn't download PDF for: {title} ({doi})***")
            else: ui.print_to_ui (f"***Couldn't download PDF for: {doi}***")
            continue
        if pdf_url and requests.get(pdf_url, headers=PDF_HEADERS).status_code == 200:
            pdf_res = requests.get(pdf_url, headers=PDF_HEADERS)
            doi_file_name = doi[-DOIS_FOR_PDF:] if doi[-DOIS_FOR_PDF] != '/' else doi[-(DOIS_FOR_PDF-1):]
            pdf = open(f'pdf{doi_file_name}.pdf', 'wb')
            pdf.write(pdf_res.content)
            pdf.close()
            downloaded += 1
            dois_pdf_dict[doi] = None
        else:
            dois_cp_dict[doi] = None
            if title:
                ui.print_to_ui (f"***Couldn't download PDF for: {title} ({doi})***")
            else: ui.print_to_ui (f"***Couldn't download PDF for: {doi}***")
        
    if downloaded != len(dois):
        ui.print_to_ui (f"\nCorrectly downloaded {downloaded} PDFs\nPlease manually add to DSpace the PDF(s) that couldn't be processed\n")
    else: ui.print_to_ui (f"\nCorrectly downloaded {downloaded} PDFs\n")
    return dois_pdf_dict, dois_cp_dict


def upload_metadata_to_dspace(ui, all_metadata, dois_pdf_dict, dois_cp_dict):
    '''
    Purpose: Upload the gathered data to DSpace
    Input: A list of lists with metadata inside per each paper and a dictionary with papers that have PDFs
    Output: N/A (New items will be created in DSpace per each paper in the list)
    '''
    global MDB_ERROR, MDB_ITEMS
    uploaded = 0
    index = -1
    DSPACE_HEADERS['Content-Type'] = 'application/json'
    for paper_metadata in all_metadata:
        
        index += 1
        data = json.dumps({"metadata": create_dspace_data(paper_metadata)})
        res = requests.post(TTUL_DSPACE_URL+f'collections/{COLLECTION_URI}/items', 
                            headers=DSPACE_HEADERS,
                            data=data)
        if res.status_code == 200:
            uploaded += 1
            split_doi = paper_metadata[3].split('/')
            for piece in split_doi:
                if '10.' in piece:
                    paper_doi = '/'.join(split_doi[split_doi.index(piece):])
                    break
            PUB_DB_DICT[paper_doi]['Handle'] = res.content.decode('utf-8').split('handle>')[1][:-2]
            # Store the uuid in the dictionary to use it for the cover page and upload the PDF
            uuid = res.content.decode('utf-8').split('UUID>')[1][:-2]
            if paper_doi in dois_pdf_dict:
                dois_pdf_dict[paper_doi] = [index, uuid]
            else: dois_cp_dict[paper_doi] = [index, uuid]
        else: 
            MDB_ERROR = 1
            ui.print_to_ui (f"***Couldn't upload this paper's metadata: {paper_metadata[3]}***")
        
    MDB_ITEMS = uploaded
    ui.print_to_ui (f"\nSuccessfully uploaded {uploaded} papers\n")


def create_dspace_data(paper):
    '''
    Purpose: Add a paper's metadata to a list following DSpace requirements
    Input: Paper metadata (list)
    Output: List with the paper's metadata following DSpace requirements
    '''
    data = []
    data.append({"key": TITLE, "value": paper[0]})
    for author in paper[1]:
        data.append({"key": AUTHORS, "value": author})
    data.append({"key": YEAR, 'value': paper[2]})
    data.append({"key": DOI, 'value': paper[3]})
    if paper[4] != None:
        for keyword in paper[4]:
            data.append({"key": KEYWORDS, 'value': keyword})
    data.append({"key": LICENSE, 'value': paper[5]})
    data.append({"key": ABSTRACT, 'value': paper[6]})
    data.append({"key": LANGUAGE, 'value': paper[7]})
    data.append({"key": TYPE, 'value': paper[8]})
    data.append({"key": CITATION, 'value': paper[9]})
    return data


def upload_pdf_to_dspace(ui, all_metadata, dois_pdf_dict):
    '''
    Purpose: Use a paper's DOI and UUID (DSpace) to upload a previously downloaded PDF 
            + merge the PDF with a newly created cover page
    Input: A dictionary with DOIs as keys and UUID as values, and the metadata
    Output: N/A (PDFs uploaded to DSpace and deleted from local space)
    0  --> Title
    5  --> License
    -1 --> Citation
    '''
    global MDB_ERROR, MDB_PDFS
    uploaded = 0
    DSPACE_HEADERS['Content-Type'] = 'application/pdf'
    for doi in dois_pdf_dict:
        # entries are initialized emtpy so we check if the handle was added
        if dois_pdf_dict[doi]:
            handle = requests.get(TTUL_DSPACE_URL + f'items/{dois_pdf_dict[doi][1]}').json()['handle']
            metadata = all_metadata[dois_pdf_dict[doi][0]]
            doi_file_name = doi[-DOIS_FOR_PDF:] if doi[-DOIS_FOR_PDF] != '/' else doi[-(DOIS_FOR_PDF-1):]
            create_cover_page(f'CP{doi_file_name}.docx', metadata[0], metadata[-1], handle, metadata[5])
            
            merger = PdfWriter()
            merger.append(f'CP{doi_file_name}.pdf')
            merger.append(f'pdf{doi_file_name}.pdf')
            merger.write(f'final{doi_file_name}.pdf')
            merger.close()
            
            pdf = open(f'final{doi_file_name}.pdf', 'rb')
            url = TTUL_DSPACE_URL + f'items/{dois_pdf_dict[doi][1]}/bitstreams?name=Main article with TTU Libraries cover page.pdf'
            res = requests.post(url, files={'file': pdf}, headers=DSPACE_HEADERS)
            pdf.close()

            os.remove(f'CP{doi_file_name}.docx')
            os.remove(f'CP{doi_file_name}.pdf')
            os.remove(f'final{doi_file_name}.pdf')
            if res.status_code == 200:
                uploaded += 1
            else:
                MDB_ERROR = 1 
                ui.print_to_ui (f"***Couldn't upload the PDF to this paper: {doi}***")
            
        os.remove(f'pdf{doi_file_name}.pdf')
    MDB_PDFS = uploaded
    ui.print_to_ui (f"\nSuccessfully uploaded {uploaded} PDFs\n")


def create_remaining_cps(ui, all_metadata, dois_cp_dict):
    '''
    Purpose: Use a paper's DOI and UUID (DSpace) to create cover pages for DOIs with no PDF
    Input: A dictionary with DOIs as keys and UUID as values, and the metadata
    Output: N/A (Cover pages for items with no PDFs are created locally)
    0  --> Title
    5  --> License
    -1 --> Citation
    '''
    for doi in dois_cp_dict:
        # entries are initialized emtpy so we check if the handle was added
        if dois_cp_dict[doi]:
            handle = requests.get(TTUL_DSPACE_URL + f'items/{dois_cp_dict[doi][1]}').json()['handle']
            metadata = all_metadata[dois_cp_dict[doi][0]]
            # Create cover pages without making them PDFs to allow additional error checking
            doi_file_name = doi[-DOIS_FOR_PDF:] if doi[-DOIS_FOR_PDF] != '/' else doi[-(DOIS_FOR_PDF-1):]
            create_cover_page(f'CP{doi_file_name}.docx', metadata[0], metadata[-1], handle, metadata[5], to_pdf=0)
    if len(dois_cp_dict)>0:
        ui.print_to_ui(f"\nCreated {len(dois_cp_dict)} cover pages (DOIs with no PDF)\n")


def store_metrics_in_db(run_time):
    '''
    Purpose: Store metrics data in a database
    Input: Run time (how long the program took to run), rest of the data is in global variables
    Output: N/A (Updates metrics database)
    '''
    if MDB_DOIS == 0:
        # doesn't store anything if there's no valid DOIs identified
        return
    db, cursor = connect_to_db()
    cursor.execute(f'INSERT INTO {METRICS_DB} (valid_dois, up_items, up_pdfs, date_ran, error, run_time) \
                    VALUES ({MDB_DOIS}, {MDB_ITEMS}, {MDB_PDFS}, "{MDB_DATE}", {MDB_ERROR}, {run_time})')
    db.commit()
    db.close()


def store_pubs_in_db():
    '''
    Purpose: Store publications and authors-publications data 
    Input: N/A (all the information is in PUB_DB_DICT)
    Output: N/A (publications and authors-publications database updated)
    '''
    db, cursor = connect_to_db()
    for doi in PUB_DB_DICT:
        # first, we need to add the publication metadata
        handle = PUB_DB_DICT[doi]["Handle"]
        cursor.execute(f'INSERT INTO {PUBLICATIONS_DB} (handle, title, doi, year_issued, date_available) \
                        VALUES ("{handle}", "{PUB_DB_DICT[doi]["Title"]}", "{doi}", {int(PUB_DB_DICT[doi]["Year"])}, {PUB_DB_DICT[doi]["Date Available"]})')
        for auth_id in PUB_DB_DICT[doi]['Authors']:
            cursor.execute(f'UPDATE {AUTHORS_DB} SET num_papers = num_papers + 1 WHERE scopus_id = "{auth_id}"')
            cursor.execute(f'INSERT INTO {COMBINED_DB} (author_id, pub_handle) \
                            VALUES ("{auth_id}", "{handle}")')
    db.commit()
    db.close()