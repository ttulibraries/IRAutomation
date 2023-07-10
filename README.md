# IRAutomation
This program is intended to receive a text file with DOIs (after the user is successfully authenticated to DSpace) and it will try to extract each paper's metadata from Scopus, download their PDFs, and upload it to DSpace. The program has been proven to upload ~15 articles (metadata and PDF) in ~3 minutes.

## How to set it up
Before running the program for the first time, open keys.py and edit the following:
  - SCOPUS_KEY: Create and paste [Scopus key](https://dev.elsevier.com/apikey/manage).
  - DSPACE_URL: The URL of the DSpace collection you want to upload to -- make sure to add `/rest/` at the end.
  - COLLECTION_URI: ID of the collection you want to upload items to. If you don't know the collection id, you can make a get request using [Collections DSpace API](https://wiki.lyrasis.org/display/DSDOC6x/REST+API#RESTAPI-Collections). 

## How to make the code an executable program 
Execute the followin command on the console (in the same folder you have the code): 
`pyinstaller upload_record.py -F`

## How to use the program
  1. Run the program.
  2. Log in to DSpace with email-password credentials.
  3. The program will open a window and you need to browse and select a text file with the DOIs of the papers you want to upload to DSpace.

      - You can either store DOIs in the text file as an actionable link or just the DOI.
  4. Read the report the program generates to see if all the papers were uploaded successfully or if you need to manually add any metadata or PDFs

## How the program works
### APIs used
  - [Dspace](https://wiki.lyrasis.org/display/DSDOC6x/REST+API) --> Upload papper's metadata and PDF
  - [Scopus](https://dev.elsevier.com/documentation/SCOPUSSearchAPI.wadl) --> Extract paper's metadata 
  - [Unpaywall](https://unpaywall.org/products/api) --> Obtain paper's PDF link

### Fields the program uploads to DSpace
  - Title
  - Creator/Author
  - Abstract
  - Language
  - Date Issued (Year)
  - Identifier.URI (DOI)
  - Subject (Keywords)
  - Description (License)
  - Type
  - Citation (created by the program following APA 7th edition standards) 

### High-level overview
Once the program obtains and validates user's credentials and the DOIs file:
  1. Search if DOI is available through Scopus.

      - If it is, get its ScopusID.
      - If it isn't skip the DOI, notify the user, and continue with the next one.
  3. Extract paper's metadata using ScopusID.
  4. Call Unpaywall (using paper's DOI and user email), obtain PDF link, and download it.

      - Notify the user if there was an error downloading PDFs.
  6. Upload new items to DSpace using the gathered metadata, PDF, and user's credentials.

      - Notify the user if there were any errors.

### Limitations
  - Metadata depends on Scopus
  - PDFs are ~75%-85% reliable for download: PDFs links come from Unpaywall (sometimes they don't have links for papers) and some publisher's websites don't allow requests that come from a program.
