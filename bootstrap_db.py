import MySQLdb
import datetime
import pandas as pd

from keys_UI import SQLDB_HOST, SQLDB_USER, SQLDB_PW, SQL_DB, \
    AUTHORS_DB, PUBLICATIONS_DB, COMBINED_DB

db = MySQLdb.connect(
            host=SQLDB_HOST,
            user=SQLDB_USER,
            passwd=SQLDB_PW,
            db=SQL_DB)
cursor = db.cursor()

path = ''               # define path for files
authors_file = ''       # define authors file name (excel)
publications_file = ''  # define publications file name (excel)
auth_pub_file = ''      # define authors-publications file name (excel)

# Load Authors DB
auth_df = pd.read_excel(path+authors_file)
last_emailed = (datetime.datetime.now()-datetime.timedelta(days=365)).strftime('%Y-%m-%d')
print ("About to store Authors data")
for index, row in auth_df.iterrows():
    if index%100==0:
        print (index)
    if cursor.execute(f'SELECT 1 FROM {AUTHORS_DB} WHERE scopus_id = "{str(row["ScopusID"])}";') == 1:
        continue
    cursor.execute(f'INSERT INTO {AUTHORS_DB} (first_name, last_name, last_emailed, hsc, scopus_id, num_papers, email, related_to, faculty) \
                    VALUES ("{row["FName"]}","{row["LName"]}","{last_emailed}", {row["HSC"]},"{row["ScopusID"]}", 0, "", NULL, 1)')
print ("Finished uploading Authors data")

# Load Publications DB
pub_df = pd.read_excel(path+publications_file)
pub_df.loc[pub_df['Date Issued'].str.contains('-'), 'Date Issued'] = pub_df.loc[pub_df['Date Issued'].str.contains('-')]['Date Issued'].apply(lambda x: x.split('-')[0])
date_format = '%Y-%m-%dT%H:%M:%SZ'
print ("About to store Publications data")
for index, row in pub_df.iterrows():
    if index%100==0:
        print (index)
    # Most of the data is already in the DB so we have to check we don't add duplicates
    if cursor.execute(f'SELECT 1 FROM {PUBLICATIONS_DB} WHERE handle = "{str(row["Handle"])}";') == 1:
        continue
    date = datetime.datetime.strptime(row['Date Available'], date_format).strftime('%Y-%m-%d')
    cursor.execute(f'INSERT INTO {PUBLICATIONS_DB} (handle, title, doi, year_issued, date_available) \
                    VALUES ("{row["Handle"]}", "{row["Title"]}", "{row["DOI"]}", {int(row["Date Issued"])}, "{date}")')
print ("Finished uploading Publications data")

# Load Authors-Publications DB
comb_df = pd.read_excel(path+auth_pub_file)
print ("About to store Authors-Publications data")
for index, row in comb_df.iterrows():
    if index%100==0:
        print (index)
    # check if we have the author in our DB
    if cursor.execute(f'SELECT 1 FROM {AUTHORS_DB} WHERE scopus_id = "{str(row["ScopusID"])}";') == 1:
        # check if we have the publication
        if cursor.execute(f'SELECT 1 FROM {PUBLICATIONS_DB} WHERE handle = "{str(row["Handle"])}";') == 1:
            # Increase the author's paper count + 1 
            cursor.execute(f'UPDATE {AUTHORS_DB} SET num_papers = num_papers + 1 WHERE scopus_id = "{row["ScopusID"]}"')
            # Store data
            cursor.execute(f"INSERT INTO {COMBINED_DB} (author_id, pub_handle) \
                            VALUES ('{row['ScopusID']}', '{row['Handle']}')")
print ("Finished uploading Authors-Publications data")

db.commit() # this saves the data
db.close()