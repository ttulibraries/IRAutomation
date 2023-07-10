# Tested-approved version, moved to production 3/27/2023
# Created by: Carlos Martinez
# Purpose: Take in a list of DOIs and upload their metadata and PDFs (if possible) to DSpace
# Metadata Format: 
#   dc.title[en_US] (title)
#   dc.creator (Authors)
#   dc.date.issued (Year)
#   dc.identifier.uri (DOI)
#   dc.subject[en_US] (Keywords)
#   dc.description[en_US] (License)
#   dc.description.abstract[en_US] (Abstract)
#   dc.language.iso[en_US] (Language)
#   dc.type[en_US] (Type)
#   dc.identifier.citation[en_US] (Citation) 
# APIs used: Scopus, Unpaywall, and DSpace

import os
import copy
import time
import json
import requests
from tkinter import filedialog


# *********** GLOBAL VARIABLES ***********
from keys import SCOPUS_KEY, DSPACE_URL, COLLECTION_URI

SCOPUS_SEARCH_API = "https://api.elsevier.com/content/search/scopus?query=doi"
SCOPUS_DETAILS_API = "https://api.elsevier.com/content/abstract/scopus_id/"
SCOPUS_HEADERS = {'X-ELS-APIKey': SCOPUS_KEY, 'Accept': 'application/json'}
UNPAYWALL_API = 'https://api.unpaywall.org/v2/'
DSPACE_HEADERS = {'Connection': 'keep-alive'}
PDF_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36 Edg/111.0.1661.62'}

EMAIL = ''        # Given by the user, used for DSpace and Unpaywall
DOIS_FOR_PDF = 6

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


def ask_dspace_cred():
    '''
    Purpose: Log in to DSpace
    Input: N/A
    Output: No output but can only get out if user is authenticated
    '''
    global EMAIL
    while True:
        email = str(input("Please enter your DSpace email: "))
        dspace_pw = str(input("Please enter your DSpace password: "))
        data = {"email": email, "password": dspace_pw}
        res = requests.post(DSPACE_URL+'login', data=data)
        if res.status_code == 200:
            EMAIL = email
            DSPACE_HEADERS['Cookie'] = f"JSESSIONID={res.cookies['JSESSIONID']}"
            print ("")
            break


def ask_dois_file():
    '''
    Purpose: Ask the user to select a txt file
    Input: N/A
    Ouput: Read only txt (with DOIs) file object
    '''
    dois_file = filedialog.askopenfile(filetypes=[('Text File', '*.txt')])
    if dois_file is None:
        # No file was selected
        print("****Error: Invalid file****")
        input("Please close this window and re-run the program ")
        exit()
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
        else:
            num_dois.append(doi)
    return num_dois


def check_duplicates(num_dois):
    '''
    Purpose: Check that we're not adding duplicates to our system
    Input: A list of DOIs given by the user
    Output: An updated list with valid DOIs (if none, program finishes)
    '''
    DSPACE_HEADERS['Content-Type'] = 'application/json'
    url = DSPACE_URL+'/items/find-by-metadata-field?expand=parentCollection'
    new_dois = copy.deepcopy(num_dois)
    print ("Checking for duplicates on DSpace")
    for doi in new_dois:
        data = json.dumps({"key": "dc.identifier.uri", "value": f'https://doi.org/{doi}'})
        res = requests.post(url, data=data, headers=DSPACE_HEADERS)
        if res.status_code == 200 and len(res.json())>0:
            for item in res.json():
                if item["parentCollection"]["uuid"] == COLLECTION_URI:
                    print (f"***{doi} already in the system***")
                    num_dois.remove(doi)
                    break
    print (f"\nNumber of valid DOIs identified: {len(num_dois)}\n")
    if len(num_dois)<1:
        print ("Not enough DOIs to execute the program")
        input("")
        exit()


def create_metadata_list(num_dois):
    '''
    Purpose: Create a list of lists with the metadata for the papers while calling the necessary APIs
    Input: Num DOIs (10.1073/pnas.2215372119)
    Output: Metadata list of lists
    '''
    all_metadata = []
    not_analyzed = []
    for doi in num_dois:
        paper_metadata = []
        res = requests.get(SCOPUS_SEARCH_API+f'({doi})', headers=SCOPUS_HEADERS).json()
        try:
            scopus_id = res['search-results']['entry'][0]['dc:identifier'].split(':')[-1]
        except KeyError:
            not_analyzed.append(doi)
            print (f"***Couldn't find {doi} on Scopus API***")
            continue
        res = requests.get(SCOPUS_DETAILS_API+scopus_id, headers=SCOPUS_HEADERS).json()["abstracts-retrieval-response"]
        try:
            store_paper_metadata(res, paper_metadata, doi)
        except Exception as e:
            print (f"***Couldn't store metadata for {doi}***")
            print (e)
            continue
        all_metadata.append(paper_metadata)
        del paper_metadata
    for doi in not_analyzed:
        num_dois.remove(doi)
    return all_metadata


def store_paper_metadata(res, paper_metadata, doi):
    '''
    Purpose: Store the paper's metadata in a list
    Input: API response and paper metadata list
    Output: N/A (Updated paper metadata list)
    '''
    # Title
    paper_metadata.append(res['coredata']['dc:title'])
    # Authors
    paper_metadata.append(store_paper_authors(res['authors']['author']))
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


def store_paper_authors(res_authors):
    '''
    Purpose: Create a list of authors 
    Input: List of authors of a given paper -- Scopus response
    Ouput: List of authors 
    '''
    authors_list = []
    for author in res_authors:
        if 'ce:given-name' in author['preferred-name']:
            first_name =  author['preferred-name']['ce:given-name']
        else: first_name = author['ce:initials']
        last_name = author['preferred-name']['ce:surname']
        full_name = last_name + ', ' + first_name
        authors_list.append(full_name)
    return authors_list


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

    Standards:
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


def download_pdfs_from_doi(dois):
    '''
    Purpose: For each DOI given to the program, download their PDF (if available)
    Input: List of DOIs
    Output: Dictionary with the DOIs that we had PDFs (each DOI is a key with null value -- will be updated later)
    '''
    downloaded = 0
    dois_pdf_dict = dict()
    for doi in dois:
        try:
            title = requests.get(UNPAYWALL_API+f'{doi}?email={EMAIL}').json()["title"]
            pdf_url = requests.get(UNPAYWALL_API+f'{doi}?email={EMAIL}').json()["best_oa_location"]['url_for_pdf']
        except TypeError:
            if title:
                print (f"***Couldn't download PDF for: {title} ({doi})***")
            else: print (f"***Couldn't download PDF for: {doi}***")
            continue
        if pdf_url and requests.get(pdf_url, headers=PDF_HEADERS).status_code == 200:
            pdf_res = requests.get(pdf_url, headers=PDF_HEADERS)
            pdf = open(f'pdf{doi[-DOIS_FOR_PDF:]}.pdf', 'wb')
            pdf.write(pdf_res.content)
            pdf.close()
            downloaded += 1
            dois_pdf_dict[doi] = None
        else:
            if title:
                print (f"***Couldn't download PDF for: {title} ({doi})***")
            else: print (f"***Couldn't download PDF for: {doi}***")
    print (f"\nCorrectly downloaded {downloaded} PDFs")
    if downloaded != len(dois):
        print ("Please manually add to DSpace the PDF(s) that couldn't be processed")
    return dois_pdf_dict


def upload_metadata_to_dspace(all_metadata, dois_pdf_dict):
    '''
    Purpose: Upload the gathered data to DSpace
    Input: A list of lists with metadata inside per each paper and a dictionary with papers that have PDFs
    Output: N/A (New items will be created in DSpace per each paper in the list)
    '''
    uploaded = 0
    index = -1
    DSPACE_HEADERS['Content-Type'] = 'application/json'
    for paper_metadata in all_metadata:
        index += 1
        data = json.dumps({"metadata": create_dspace_data(paper_metadata)})
        res = requests.post(DSPACE_URL+f'collections/{COLLECTION_URI}/items', 
                            headers=DSPACE_HEADERS,
                            data=data)
        if res.status_code == 200:
            uploaded += 1
            split_doi = '/'.join(paper_metadata[3].split('/')[-2:])
            for piece in split_doi:
                if '10.' in piece:
                    paper_doi = '/'.join(split_doi[split_doi.index(piece):])
                    break
            if paper_doi in dois_pdf_dict:
                # Store the handle in the dictionary to use it when uploading the PDF
                uuid = res.content.decode('utf-8').split('UUID>')[1][:-2]
                dois_pdf_dict[paper_doi] = [index, uuid]
        else: print (f"***Couldn't upload this paper's metadata: {paper_metadata[3]}***")
    print (f"\nSuccessfully uploaded {uploaded} papers\n")


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


def upload_pdf_to_dspace(dois_pdf_dict):
    '''
    Purpose: Use a paper's DOI and UUID (DSpace) to upload a previously downloaded PDF 
    Input: A dictionary with DOIs as keys and UUID as values, and the metadata
    Output: N/A (PDFs uploaded to DSpace and deleted from local space)
    0  --> Title
    5  --> License
    -1 --> Citation
    '''
    uploaded = 0
    DSPACE_HEADERS['Content-Type'] = 'application/pdf'
    for doi in dois_pdf_dict:
        doi_file_name = doi[-DOIS_FOR_PDF:] if doi[-DOIS_FOR_PDF] != '/' else doi[-(DOIS_FOR_PDF-1):]
        if dois_pdf_dict[doi_file_name]:            
            pdf = open(f'pdf{doi_file_name}.pdf', 'rb')
            url = DSPACE_URL + f'items/{dois_pdf_dict[doi][1]}/bitstreams?name={doi}.pdf'
            res = requests.post(url, files={'file': pdf}, headers=DSPACE_HEADERS)
            pdf.close()
            if res.status_code == 200:
                uploaded += 1
            else: print (f"***Couldn't upload the PDF to this paper: {doi}***")
        os.remove(f'pdf{doi_file_name}.pdf')
    print (f"\nSuccessfully uploaded {uploaded} PDFs")


def main():
    ask_dspace_cred()
    dois_file = ask_dois_file()
    num_dois = read_dois(dois_file)
    start = time.time()
    check_duplicates(num_dois)
    all_metadata = create_metadata_list(num_dois)
    dois_pdf_dict = download_pdfs_from_doi(num_dois)
    upload_metadata_to_dspace(all_metadata, dois_pdf_dict)
    upload_pdf_to_dspace(dois_pdf_dict)
    print(f"\nElapsed Time: {time.time()-start:.2f}")
    input("")


if __name__ == '__main__': 
    main()