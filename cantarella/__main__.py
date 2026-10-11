# AnimeDL — compatibility shim.
# The unified entry point lives in main.py; this keeps `python -m cantarella`
# (used by the anime core's /restart) working.
import main

if __name__ == "__main__":
    main.main()
