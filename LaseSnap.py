import tkinter as tk
from tkinter import ttk


# Function to simulate sending commands to the devices
def execute_commands():
    for child in tree.get_children():
        wavelength = tree.item(child)["values"][0]
        num_pictures = tree.item(child)["values"][1]

        for i in range(num_pictures):
            # Simulating sending 'gowave' command to TLS machine
            print(f"Simulating TLS Command: gowave {wavelength}")

            # Simulating sending trigger to Arduino
            print("Simulating Arduino Trigger")
            # Normally here you'd call the send_trigger() function

            # Add a delay to simulate time taken for each operation
            root.after(1000)

##### Addded new row
# Function to add a new row to the table
def add_row():
    wavelength = wavelength_entry.get()
    num_pictures = pictures_entry.get()

    # Add the new row to the Treeview
    tree.insert("", "end", values=(wavelength, num_pictures))


# Set up the main application window
root = tk.Tk()
root.title("Laboratory Equipment Control")

# Create the Treeview widget
columns = ("Wavelength", "Number of Pictures")
tree = ttk.Treeview(root, columns=columns, show="headings")
tree.heading("Wavelength", text="Wavelength (nm)")
tree.heading("Number of Pictures", text="Number of Pictures")
tree.pack(fill=tk.BOTH, expand=True)

# Frame for adding new rows
input_frame = tk.Frame(root)
input_frame.pack(fill=tk.X)

# Input fields for wavelength and number of pictures
tk.Label(input_frame, text="Wavelength:").pack(side=tk.LEFT, padx=5, pady=5)
wavelength_entry = tk.Entry(input_frame)
wavelength_entry.pack(side=tk.LEFT, padx=5, pady=5)

tk.Label(input_frame, text="Number of Pictures:").pack(side=tk.LEFT, padx=5, pady=5)
pictures_entry = tk.Entry(input_frame)
pictures_entry.pack(side=tk.LEFT, padx=5, pady=5)

# Button to add a new row
add_button = tk.Button(input_frame, text="Add Row", command=add_row)
add_button.pack(side=tk.LEFT, padx=5, pady=5)

# Button to execute the commands
execute_button = tk.Button(root, text="Execute Commands", command=execute_commands)
execute_button.pack(pady=10)

# Run the application
root.mainloop()
