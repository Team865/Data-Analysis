import os
import time
from re import compile

import numpy as np
import pandas as pd

from src.model import database, format_time, boards, entrylib

FILTER_HEADER = ['Match', 'Team', 'Name', "Board", "Edited"]
FILTER_SORT = ['Match', 'Team']


class VerificationManager:
    """Data model manager for verifying scouting entries"""

    @staticmethod
    def list_files(dir_path):
        """Search for CSV files"""
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f.split(".")[-1].lower() == "csv":
                    yield os.path.join(root, f)

    def __init__(self, db_path, csv_dir_path, board_dir_path):
        """
        Initializes the manager by providing file paths required \
        to manage the process of verification.
        This method does not actually load any data because the
        intention at this point may not be clear
        :param db_path: path to the database file (.warp7)
        :param csv_dir_path: path to the directory of the scanned data
        :param board_dir_path: path to the direction containing boards
        """

        self.db_path = db_path
        self.csv_dir_path = csv_dir_path
        self.board_dir_path = board_dir_path

        self.board_finder = boards.Finder(board_dir_path)

        if os.path.exists(db_path):
            conn = database.get_engine(db_path).connect()
            self.raw_entries = pd.read_sql(sql="SELECT * FROM RAW_ENTRIES",
                                           con=conn,
                                           index_col="index")

            self.edited_entries = pd.read_sql(sql="SELECT * FROM EDITED_ENTRIES",
                                              con=conn,
                                              index_col="index")
            conn.close()
        else:
            self.raw_entries = pd.DataFrame(columns=database.RAW_HEADER.keys())
            self.edited_entries = pd.DataFrame(columns=database.EDITED_HEADER.keys())
            self.update()
            self.save()

    def __getitem__(self, index):
        """
        Get data for one specific entry based on the index
        :param index: the index to lookup
        :return: The entry info, or raises exception if does not exist
        """

        if index in self.edited_entries.index:
            row = self.edited_entries.iloc[index]
            raw = None
            if row["RawIndex"] in self.raw_entries.index:
                raw = entrylib.Entry(self.raw_entries.iloc[row["RawIndex"]], self.board_finder)
            edited = entrylib.Entry(row, self.board_finder)
            last_edit_time = row["Edited"]

            return raw, edited, last_edit_time

        raise IndexError()

    def __setitem__(self, index, value: entrylib.Entry):
        """
        Sets a modified entry object into the manager
        :param index: the index to lookup
        :param value: the entry object to set
        """

        if index in self.edited_entries.index:
            value.encode()

            self.edited_entries.at[index, "Match"] = value.match
            self.edited_entries.at[index, "Team"] = value.team
            self.edited_entries.at[index, "Name"] = value.name
            self.edited_entries.at[index, "StartTime"] = value.start_time
            self.edited_entries.at[index, "Comments"] = value.comments
            self.edited_entries.at[index, "Data"] = value.encoded_data
            self.edited_entries.at[index, "Edited"] = format_time.display_time(time.time())
            return

        raise IndexError()

    def update(self):
        """
        Updates the two analysis with new data saved in the csv dir path
        Directly replaces the raw data table
        Attempts to merge the raw data into the edited data
        :return: The number of new items imported
        """

        def read_one(f_path):
            """Read the contents of one CSV file"""
            read_file = open(f_path, "r")
            entries = read_file.readlines()
            read_file.close()
            for entry in entries:
                yield "".join(entry.split(",")[:-1])

        def read_all():
            """Read all found files and returns ordered unique entries that pass the format test"""
            matcher = compile("\d{1,3}_\d{1,4}_[^_]+_[0-9a-f]{8}_[0-9a-f]{8}_([0-9a-f]{4})*_.*")
            unique_entries = []

            for f in self.list_files(self.csv_dir_path):
                for entry in read_one(f):
                    if matcher.match(entry) is not None:
                        if entry not in unique_entries:
                            unique_entries.append(entry)

            return unique_entries

        def make_columns(entry):
            """Make the columns to put in the database"""
            split = entry.split("_")
            return {"Match": int(split[0]),
                    "Team": int(split[1]),
                    "Name": split[2],
                    "StartTime": format_time.display_time(int(split[3], 16)),
                    "Board": self.board_finder.get_board_by_id(int(split[4], 16)).name(),
                    "Data": split[5],
                    "Comments": split[6]
                    }

        # Create the DataFrame
        # TODO Must make unique entries so that we don't rely on older system
        self.raw_entries = pd.DataFrame([make_columns(e) for e in read_all()],
                                        columns=database.RAW_HEADER.keys())
        self.merge()

    def merge(self):
        # Compute a boolean array indicating the add values to raw
        condition = ~self.raw_entries.index.isin(self.edited_entries["RawIndex"].dropna())

        # Filter by the condition to get new data values
        new_data = self.raw_entries[condition].reset_index()

        new_data.rename(columns={"index": "RawIndex"},
                        inplace=True)

        new_data["Edited"] = " "
        new_data = new_data[list(database.EDITED_HEADER.keys())]

        # Add new data to the edited table
        self.edited_entries = pd.concat([self.edited_entries, new_data],
                                        ignore_index=True)

    def save(self):
        conn = database.get_engine(self.db_path).connect()
        self.raw_entries.to_sql(name="RAW_ENTRIES",
                                con=conn,
                                if_exists="replace",
                                dtype=database.RAW_HEADER
                                )

        self.edited_entries.to_sql(name="EDITED_ENTRIES",
                                   con=conn,
                                   if_exists="replace",
                                   dtype=database.EDITED_HEADER,
                                   index_label="index")

    def write_csv(self, target_path):
        target_file = open(target_path, "w")
        for _, row in self.search().iterrows():
            items = map(str, [row["Match"],
                              row["Team"],
                              row["Name"],
                              hex(format_time.parse_display(row["StartTime"]))[2:],
                              self.board_finder.get_board_by_name(row["Board"]).specs["id"],
                              row["Data"],
                              row["Comments"]])

            line = "_".join(items)
            line += ", "
            line += format_time.display_time(time.time())
            print(line, file=target_file)
        target_file.close()

    def search(self, **kwargs):
        """
        Searches the database of entries to show relevant results

        Parameters
        ----------
        team: Team number: List of ints
        match: Match number: List of ints
        name: Scout name: List of scout names

        Items in these list are applied with OR logic

        :return: A DataFrame with search results. It is a slice of self.edited_entries
        """

        # Clean the input keyword arguments
        search_rules = {k.capitalize(): kwargs[k] for k in kwargs.keys() if kwargs[k]}

        if "Match" in search_rules.keys():
            matches = search_rules["Match"]
            possible_matches = set()
            for available_match in self.edited_entries["Match"].unique():
                for match in matches:
                    if str(available_match).startswith(str(match)):
                        possible_matches.add(available_match)
            search_rules["Match"] = possible_matches

        if "Team" in search_rules.keys():
            teams = search_rules["Team"]
            possible_teams = set()
            for available_team in self.edited_entries["Team"].unique():
                for team in teams:
                    if str(available_team).startswith(str(team)):
                        possible_teams.add(available_team)
            search_rules["Team"] = possible_teams

        if "Name" in search_rules.keys():
            names = search_rules["Name"]
            possible_names = set()
            for available_name in self.edited_entries["Name"].unique():
                for name in names:
                    if name.lower() in available_name.lower():
                        possible_names.add(available_name)
            search_rules["Name"] = possible_names

        results = self.edited_entries

        for i in search_rules.keys():
            if i in FILTER_HEADER:
                results = results[results[i].isin(search_rules[i])]

        return results.sort_values(by=FILTER_SORT)

    def match_row(self, match, team, name):
        """
        Simpler and more efficient way of matching match, team, and name than search
        :param match:
        :param team:
        :param name:
        :return: a matching row, or an empty DataFrame if entry doesn't exist
        """
        return self.edited_entries[(self.edited_entries["Match"] == match) &
                                   (self.edited_entries["Team"] == team) &
                                   (self.edited_entries["Name"] == name)]

    def append(self, **kwargs):
        """
        Add a new entry to the data
        :param kwargs: entry info dictionary
        :return: The new entry info, or old if match, team, and name already exists
        """

        entry_data = {k.capitalize(): kwargs[k] for k in kwargs.keys()}

        match = entry_data.get("Match")
        team = entry_data.get("Team")
        name = entry_data.get("Name")

        matching_row = self.match_row(match, team, name)

        if matching_row.empty:
            new_data = pd.DataFrame([{
                "Match": match,
                "Team": team,
                "Name": name,
                "StartTime": format_time.display_time(time.time()),
                "Board": self.board_finder.get_first().name(),
                "Data": "",
                "Comments": "",
                "RawIndex": np.nan,
                "Edited": ""

            }], columns=database.EDITED_HEADER.keys())

            self.edited_entries = pd.concat([self.edited_entries, new_data], ignore_index=True)

            return self[self.match_row(match, team, name).index[0]]

        return self[matching_row.index[0]]
