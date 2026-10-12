"""
This module provides functions to download, convert, and compress images, and then convert them into a PDF file.

Copy right (c):-  Rahat4089 and VOATcb
Modified:- Dra-Sama
"""

from pathlib import Path
from PIL import Image, UnidentifiedImageError
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from loguru import logger
import os

import pillow_avif  # This registers AVIF format support with Pillow
import pillow_heif

import requests
import shutil

from cloudscraper import create_scraper
from asyncio import to_thread
import asyncio

import PyPDF2

def thumbnali_images(image_url, download_dir, quality=80, file_name="thumb.jpg"):
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    
    image_response = requests.get(image_url)
    if image_response.status_code == 200:
        img_path = os.path.join(download_dir, file_name)
        with open(img_path, 'wb') as img_file:
            img_file.write(image_response.content)
        
        return img_path
    else:
        return None


async def download_and_convert_images(
    images, 
    download_dir,
    base_url: str,
    quality=60, 
    target_width=None, 
    cs=None
):
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    image_files = []
    if "manhuaplus.com" in base_url:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://manhuaplus.com/",
            #"Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": base_url,
        }
    
    for idx, image_url in enumerate(images, 1):
        retries = 0
        while retries < 4:
            if cs:
                scarper = create_scraper()
                image_response = await to_thread(scarper.get, image_url, headers=headers)
            else:
                image_response = await to_thread(requests.get, image_url, stream=True, headers=headers)#, verify=False)
            if image_response.status_code == 200:
                img_path = os.path.join(download_dir, f"{idx}.jpg")
                if os.path.exists(download_dir):
                    with open(img_path, 'wb') as img_file:
                        img_file.write(image_response.content)
                        try:
                            with Image.open(img_path) as img:
                                img = img.convert("RGB")
                                img_width, img_height = img.size
                                if target_width:
                                    new_height = int((target_width / img_width) * img_height)
                                    img = img.resize((target_width, new_height), Image.LANCZOS)
                                    img.save(img_path, "JPEG", quality=quality, optimize=True)
                        except Exception as e:
                            logger.exception(f"Error converting image: {e}")
                        
                        image_files.append(img_path)
                        break
                else:
                     raise Exception("Tasks cancelled")
                    
            else:
                logger.exception(f"Download :- {retries} :- {image_url}: {image_response.text}")
                retries += 1

    return image_files


def compress_image(image_path, output_path, quality=80, target_width=None):
    """Compress the image by resizing and reducing its quality."""
    try:
        img = Image.open(image_path).convert("RGB")
        img_width, img_height = img.size

        if target_width:
            new_height = int((target_width / img_width) * img_height)
            img = img.resize((target_width, new_height), Image.LANCZOS)

        img.save(output_path, "JPEG", quality=quality, optimize=True)
        return output_path
    except Exception as e:
        logger.error(f"Error compressing image {image_path}: {e}")
        return image_path


def convert_images_to_pdf(image_files, pdf_output_path, compressed_dir, password=None, compression_quality=50):
    if not image_files:
        logger.warning("No images provided for PDF conversion.")
        return "No images provided for PDF conversion."

    if not os.path.exists(compressed_dir):
        os.makedirs(compressed_dir)
    
    temp_pdf_path = str(pdf_output_path).replace(".pdf", "_temp.pdf")
    
    c = canvas.Canvas(str(temp_pdf_path), pagesize=letter)

    # Set the target width (e.g., the width of the smallest image)
    try: target_width = min(Image.open(image_file).width for image_file in image_files)
    except: target_width = None

    def draw_image(image_file):
        try:
            img = Image.open(image_file)
            img_width, img_height = img.size
            # Calculate the new height maintaining the aspect ratio
            new_height = int(target_width * img_height / img_width)
            c.setPageSize((target_width, new_height))
            c.drawImage(str(image_file), 0, 0, width=target_width, height=new_height)
            c.showPage()  # Create a new page for each image
        except Exception as e:
            logger.error(f"Failed to process image {image_file}: {e}")

    # Process and compress the images
    compressed_images = []
    for image_file in image_files:
        compressed_image_path = f"{compressed_dir}/{os.path.basename(image_file)}"
        compressed_image = compress_image(image_file, compressed_image_path, quality=compression_quality, target_width=target_width)
        compressed_images.append(compressed_image)
        draw_image(compressed_image)

    c.save()
    
    if password:
        encrypt_pdf(temp_pdf_path, str(pdf_output_path), password)
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)  # Remove the temporary unprotected PDF
    else:
        os.rename(temp_pdf_path, str(pdf_output_path))

    shutil.rmtree(compressed_dir, ignore_errors=True)
    #for image_file in image_files:
        #os.remove(image_file)

    logger.info(f"Compressed PDF created at {pdf_output_path}")
    return None


def encrypt_pdf(input_path, output_path, password):
    """Encrypt a PDF with a password using PyPDF2"""
    try:
        with open(input_path, 'rb') as input_file:
            reader = PyPDF2.PdfReader(input_file)
            writer = PyPDF2.PdfWriter()

            # Add all pages to the writer
            for page in reader.pages:
                writer.add_page(page)

            # Encrypt the PDF
            writer.encrypt(user_password=password, owner_password=None, 
                          use_128bit=True)

            # Save the encrypted PDF
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)

    except Exception as e:
        logger.error(f"Failed to encrypt PDF: {e}")
        
