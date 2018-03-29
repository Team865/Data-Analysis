"""
Manages all the entered entries for navigation
A list of all entries
"""

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from processor import database, board, decoder

FILTER_HEADER = ['Match', 'Team', 'Name', "Board", "Edited"]
FILTER_SORT = ['Match', 'Team']


class EntryManager:

    def __init__(self, db_file, board_path):
        """
        Loads raw data and edited data from database
        :param db_file: the database file to read from
        """

        self.finder = board.Finder(board_path)

        self.database_file = db_file

        engine = database.get_engine(self.database_file)
        conn = engine.connect()

        try:
            # Read the entire table but use 'index' as the table index
            self.original_data = pd.read_sql(sql="SELECT * FROM RAW_ENTRIES",
                                             con=conn,
                                             index_col="index")

            # Check if we use the existing EDITED_ENTRIES table or create a new one
            if engine.dialect.has_table(connection=conn,
                                        table_name="EDITED_ENTRIES"):

                self.edited_data = pd.read_sql(sql="SELECT * FROM EDITED_ENTRIES",
                                               con=conn,
                                               index_col="index")

                # Compute a boolean array indicating the add values to raw
                condition = ~self.original_data.index.isin(self.edited_data["RawIndex"].dropna())

                # Filter by the condition to get new data values
                new_data = self.original_data[condition].reset_index()

                new_data.rename(columns={"index": "RawIndex"},
                                inplace=True)

                new_data["Edited"] = " "

                # Add new data to the edited table
                self.edited_data = pd.concat([self.edited_data, new_data],
                                             ignore_index=True)

            else:
                self.edited_data = self.original_data.reset_index()

                self.edited_data.rename(columns={"index": "RawIndex"},
                                        inplace=True)

                self.edited_data["Edited"] = " "

        except SQLAlchemyError as error:
            self.original_data = pd.DataFrame(columns=database.RAW_HEADER.keys())
            self.edited_data = pd.DataFrame(columns=database.EDITED_HEADER.keys())
            print(error)

        finally:
            conn.close()

    def filter(self, **kwargs):
        """
        Filters the database of entries to show relevant results

        Parameters
        ----------
        team: Team number
        match: Match number
        name: Scout name
        board: Board
        edited: Time edited

        :return: A filtered DataFrame match the criteria
        """

        filters = {k.capitalize(): kwargs[k] for k in kwargs.keys()}

        df = self.edited_data

        for i in filters.keys():
            if i in FILTER_HEADER:
                df = df[df[i].isin(filters[i])]

        return df.sort_values(by=FILTER_SORT)[FILTER_HEADER].reset_index()

    def data_row_at(self, index):
        if index in self.edited_data.index:
            return self.edited_data.iloc[index]
        return None

    def entry_at(self, index):
        """
        Get data for one specific entry based on the index
        :param index: the index to lookup
        :return: The entry info, or empty dict if row does not exist
        """

        row = self.data_row_at(index)

        if row is not None:
            entry_board = self.finder.get_board_by_name(row["Board"])
            entry_info = {k: row[k] for k in ["Match", "Team", "Name", "StartTime", "Comments"]}
            entry_info["Board"] = entry_board.name()
            entry_info["Data"] = list(decoder.decode(row["Data"], entry_board))
            return entry_info

        return {}

    def get_relative_entry(self, filtered_table, current_index, increment_by):
        """
        Get a entry from a filtered table relative to a filtered tab;e
        :param filtered_table: Filtered table(pandas) as generated by filter
        :param current_index: The index to increment from
        :param increment_by: The number of rows to increment by
        :return: The entry info for the selected entry (from entry_at)
        """

        indices = list(filtered_table["index"].values)

        if len(indices) != 0:
            if current_index in indices:
                return self.entry_at(indices[(indices.index(current_index) + increment_by) % len(indices)])
            return self.entry_at(indices[0])
        return {}

    def next(self, filtered_table, current_index):
        return self.get_relative_entry(filtered_table, current_index, 1)

    def previous(self, filtered_table, current_index):
        return self.get_relative_entry(filtered_table, current_index, -1)

    def get_matching_row(self, match, team, name):
        """
        Simpler and more efficient way of matching match, team, and name than filter
        :param match:
        :param team:
        :param name:
        :return: a matching row, or an empty DataFrame if entry doesn't exist
        """
        return self.edited_data[(self.edited_data["Match"] == match) &
                                (self.edited_data["Team"] == team) &
                                (self.edited_data["Name"] == name)]

    def add_entry(self, **kwargs):
        """
        Add a new entry to the data
        :param kwargs: entry info dictionary
        :return: The new entry info, or old if match, team, and name already exists
        """

        entry_data = {k.capitalize(): kwargs[k] for k in kwargs.keys()}

        match = entry_data.get("Match");
        team = entry_data.get("Team")
        name = entry_data.get("Name")

        matching_row = self.get_matching_row(match, team, name)

        if matching_row.empty:
            return None

        return self.entry_at(matching_row.index[0])

    def remove_entry(self, match, team, name, index_value):
        match_at_index = str(self.edited_data.loc[index_value, "Match"])
        print(match_at_index)
        team_at_index = str(self.edited_data.loc[index_value, "Team"])
        print(team_at_index)
        name_at_index = str(self.edited_data.loc[index_value, "Name"])
        print(name_at_index)

        match_correct = match_at_index == match
        team_correct = team_at_index == team
        name_correct = name_at_index == name

        if match_correct and team_correct and name_correct:
            self.edited_data.drop(index=index_value, inplace=True)

    def edit_entry(self, index, data):
        # Used to change data for one entry

        # TODO Call the board to get data type #
        # TODO Call validation and format parser
        # TODO call the encoder
        self.edited_data.set_value(index, "Data", data)

    def revert_entry(self, index):
        pass

    def save(self):

        conn = database.get_engine(self.database_file).connect()

        self.edited_data.to_sql(name="EDITED_ENTRIES",
                                con=conn,
                                if_exists="replace",
                                dtype=database.EDITED_HEADER,
                                index_label="index")

        conn.close()


if __name__ == "__main__":
    # Do Testing Here

    entry_manager = EntryManager("../data/database/data.warp7", "../data/board/")
    a = entry_manager.filter(match=[5])
    print(a)
    print(entry_manager.get_relative_entry(entry_manager.filter(match=[5]), 242, 1))
    entry_manager.save()

    print(entry_manager.add_entry(match=100, team=200, name=300))

    # print(entry_manager.remove_entry(42, 4152, "Sam.s", 2))
    # print(entry_manager.edited_data)
