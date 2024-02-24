import streamlit as st
from PIL import Image
import subprocess
import requests
from io import BytesIO
import re
import numpy as np
import audioread
import moviepy.editor as mpe
from openai import OpenAI
from moviepy.editor import ImageClip, concatenate_videoclips, TextClip
import boto3
from botocore.exceptions import NoCredentialsError
import certifi
import requests
import os
import urllib.request
from urllib.request import urlopen
import ssl
import json
import tempfile
import time

 
# ts stores the time in seconds
ts = time.time()
 
# print the current timestamp
print(ts)

ssl._create_default_https_context = ssl._create_unverified_context
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Specify your AWS credentials and region
aws_access_key_id = st.secrets.aws_access_key_id
aws_secret_access_key = st.secrets.aws_secret_access_key
aws_region =st.secrets.aws_region

# Initialize Streamlit app
st.title("NarrativeVision Generator")

# Create a text input widget for the user to input their script
text_script = st.text_area("Enter the text script for the video:")

# Create a button to trigger the AI video generation
if st.button("Generate Video"):
    if text_script:
        st.write("Generating video, please wait...")

        api_key =st.secrets.openai_api_key
        client = OpenAI(api_key=api_key)

        no_of_image = 10

        response = client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system",
                 "content": "You are a skilled GPT-4 AI with specialized abilities in understanding and interpreting video scripts. Your expertise includes generating precise and imaginative prompts for DALL-E-3, ensuring they align with DALL-E-3's content policy. You are adept at identifying key visual elements, themes, and moods from the text and translating them into creative, policy-compliant image prompts."},
                {"role": "user", "content": f"Here is the text script of a video provided by the user: {text_script}. Analyze this script and identify {no_of_image} distinct scenes or key elements that are visually striking or central to the script's narrative. Based on your analysis, create {no_of_image} separate and detailed prompts for generating images using DALL-E-3. These prompts should be clear, imaginative, and fully compliant with DALL-E-3's content policy. Ensure that they are tailored to vividly represent the chosen scenes or elements from the script."},
                {"role": "system", "content": "json_object"}
            ]
        )

        text_prompt = response.choices[0].message.content

        print(text_prompt)

        # Split the prompts into separate items
        prompts = text_prompt.split(":")[1]

        img_prompts = re.split(r'",', prompts)

        image_urls = []

        st.write("Our smart AI 😎 is generating image prompt for your video.")

        for prompt in img_prompts:
            print(prompt + """ ". """)
            st.write("Prompt: ", prompt + """ ". """)
            response = client.images.generate(
                model="dall-e-3",
                prompt=str(prompt + """ ". """),
                size="1024x1792",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            image_urls.append(image_url)

        s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key, region_name=aws_region)
        s3_bucket_name = 'reel-generator'  # Replace with your S3 bucket name
        s3_images_prefix = f'images{ts}/' 

        for i, url in enumerate(image_urls):
            response = requests.get(url)
            if response.status_code == 200:
                image_bytes = BytesIO(response.content)
                print(image_bytes)
                image_filename = f"image_{i + 1}.jpg"
                s3_object_key = f"images{ts}/{image_filename}"  # Adjust the S3 object key as needed
                try:
                    s3.upload_fileobj(image_bytes, s3_bucket_name, s3_object_key)
                    st.write(f"{image_filename} successfully generated and saved to S3.")
                except NoCredentialsError:
                    st.write(f"Failed to upload {image_filename} to S3 due to missing AWS credentials.")
            else:
                st.write(f"Failed to download image {i + 1} from {url}.")

        response = client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=f"{text_script}",
        )
        audio_bytes = BytesIO(response.content)

        s3_object_key_audio = f"audio{ts}/output.mp3"  # Adjust the S3 object key for audio

        try:
            s3.upload_fileobj(audio_bytes, s3_bucket_name, s3_object_key_audio)
            st.write("Audio successfully generated and saved to S3.")
        except NoCredentialsError:
            st.write("Failed to upload audio to S3 due to missing AWS credentials.")

        st.write("Our smart AI 😎 has generated Audio for your video. 🔊 ")

        image_urls = []

        try:
            objects = s3.list_objects(Bucket=s3_bucket_name, Prefix=s3_images_prefix)
            for obj in objects.get('Contents', []):
                image_url = s3.generate_presigned_url('get_object', Params={'Bucket': s3_bucket_name, 'Key': obj['Key']})
                image_urls.append(image_url)
        except NoCredentialsError:
            st.write("Failed to fetch images from S3 due to missing AWS credentials.")

        # Fetch audio from S3 bucket
        s3_audio_key = f'audio{ts}/output.mp3'  # Adjust the S3 object key for audio

        try:
            audio_url = s3.generate_presigned_url('get_object', Params={'Bucket': s3_bucket_name, 'Key': s3_audio_key})
        except NoCredentialsError:
            st.write("Failed to fetch audio from S3 due to missing AWS credentials.")

        st.write("Our smart AI 😎 has fetched the necessary assets for your video.")

        # Calculate the duration of each image in the video
        audio_clip = mpe.AudioFileClip(audio_url)
        total_duration = audio_clip.duration
        no_of_images = len(image_urls)
        image_duration = total_duration / no_of_images


        # Create video from fetched images and audio
        clips = [mpe.ImageClip(url).set_duration(image_duration) for url in image_urls]
        video_clip = mpe.concatenate_videoclips(clips, method="compose")
        video_clip = video_clip.set_audio(audio_clip)

        # Set the frames per second (fps) for the video
        video_clip.fps = 60  # Adjust the fps value as needed

        # Create an in-memory BytesIO object to write the video to
        video_bytes_io = BytesIO()

        # Upload the video to S3 bucket directly
        s3_video_key = f'videos{ts}/output_video.mp4'  # Adjust the S3 object key for the video

        # Create a temporary file to save the video
        with tempfile.NamedTemporaryFile(suffix='.mp4') as temp_video_file:
            temp_video_path = temp_video_file.name
            video_clip.write_videofile(temp_video_path, codec='libx264', audio_codec='aac')
            temp_video_file.seek(0)  # Reset the position to the beginning of the file

            # Upload the temporary video file to S3 bucket
            try:
                s3.upload_file(temp_video_path, s3_bucket_name, s3_video_key)
                st.write("Video successfully generated and saved to S3.")
            except NoCredentialsError:
                st.write("Failed to upload video to S3 due to missing AWS credentials.")

        st.write("video generation complete! 🥳")

        final_url = s3.generate_presigned_url('get_object', Params={'Bucket': s3_bucket_name, 'Key': s3_video_key})

        # Embed the video using HTML5 video player
        st.write(f"Here's your generated video:")
        st.write(f'<video width="360" height="640" controls><source src="{final_url}" type="video/mp4"></video>', unsafe_allow_html=True)





    else:
        st.warning("Please enter a text script for the video.")



# Display instructions to the user
st.write("Instructions:")
st.write("1. Enter the text script for the video in the text area.")
st.write("2. Click the 'Generate Video' button to create the AI-generated video.")
st.write("3. The video video will be displayed, and you can download the audio separately.")
st.write("4. You may get BadRequest Error. In that case just regenerate.")
st.write("5. Text script has a limit of 4096 characters.")
st.write("Please wait, it generally takes 5-10 minutes to generate the video.")
