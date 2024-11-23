# src/services/cloudinary_service.py

import os
from dotenv import load_dotenv
from cloudinary import config, uploader
import cloudinary.exceptions

# Load environment variables from .env file in the project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

# Configure Cloudinary
config(
    cloud_name=os.getenv('CLOUDINARY_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_SECRET_KEY')
)

def upload_image(image_data, folder, filename):
    """
    Upload an image to Cloudinary.

    :param image_data: The image data (can be a file-like object, URL, or base64 encoded string)
    :param folder: The folder in Cloudinary where the image should be stored
    :param filename: The filename to use for the image in Cloudinary
    :return: A dictionary containing the upload result, or None if upload failed
    """
    try:
        result = uploader.upload(image_data, folder=folder, public_id=filename, use_filename=True, unique_filename=False)
        return result
    except cloudinary.exceptions.Error as e:
        print(f"Error uploading image to Cloudinary: {str(e)}")
        return None

def get_image_url(public_id):
    """
    Get the URL of an image stored in Cloudinary.

    :param public_id: The public ID of the image in Cloudinary
    :return: The URL of the image
    """
    return cloudinary.CloudinaryImage(public_id).build_url()

# src/services/cloudinary_service.py

from cloudinary import api

# ... (keep your existing imports and functions)

def folder_exists(folder_path):
    """
    Check if a folder exists in Cloudinary.

    :param folder_path: The path of the folder to check
    :return: True if the folder exists, False otherwise
    """
    try:
        # List the contents of the folder
        result = api.resources(type="upload", prefix=folder_path, max_results=1)
        # If the folder exists and is not empty, it will have a 'resources' key
        return 'resources' in result and len(result['resources']) > 0
    except Exception as e:
        print(f"Error checking folder existence: {str(e)}")
        return False

def file_exists(folder, filename):
    """
    Check if a file exists in a folder in Cloudinary.

    :param folder: The folder where the file is stored
    :param filename: The filename to check
    :return: True if the file exists, False otherwise
    """
    try:
        # List the contents of the folder
        result = api.resources(type="upload", prefix=f"{folder}/{filename}", max_results=1)
        # If the file exists, it will have a 'resources' key
        return 'resources' in result and len(result['resources']) > 0
    except Exception as e:
        print(f"Error checking file existence: {str(e)}")
        return False
