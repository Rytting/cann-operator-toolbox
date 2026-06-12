#!/usr/bin/env python3
"""Launch the CANN toolbox GUI."""

from src.cann_toolbox_app import CANNToolbox
import tkinter as tk


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    CANNToolbox(root)
    root.mainloop()


if __name__ == "__main__":
    main()
