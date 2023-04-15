import grpc
from concurrent import futures
import protos.chat_pb2 as chat_pb2
import protos.chat_pb2_grpc as chat_pb2_grpc
from google.protobuf import json_format
import argparse
import json
import re
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import sys
from db import DiscussionsDB, Discussion
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
    send_from_directory
)
from pyllamacpp.model import Model
from queue import Queue
from pathlib import Path
import gc
app = Flask("GPT4All-WebUI", static_url_path="/static", static_folder="static")
import time
from config import load_config
import threading
import requests
import json

class ChatbotInstance():
    def new_text_callback(self, text: str):
        print(text, end="")
        sys.stdout.flush()

    def generate_message(self):
        self.generating=True
        self.text_queue=Queue()
        gc.collect()

        reply = self.chatbot_bindings.generate(
            self.prompt_message,#self.full_message,#self.current_message,
            n_predict=len(self.current_message)+self.config['n_predict'],
            temp=self.config['temp'],
            top_k=self.config['top_k'],
            top_p=self.config['top_p'],
            repeat_penalty=self.config['repeat_penalty'],
            repeat_last_n = self.config['repeat_last_n'],
            #seed=self.config['seed'],
            n_threads=8
        )
        # reply = self.chatbot_bindings.generate(self.full_message, n_predict=55)
        self.generating=False
        return reply

    def restore_discussion(self, id):
        self.chatbot_bindings = self.create_chatbot()
        self.current_discussion = Discussion(id, self.db)

        messages = self.current_discussion.get_messages()
        if not messages:
            messages = ['']
        self.prompt_message = ""
        for i in range(min(len(messages), 3)):
            self.prompt_message += "{}: {} \n".format(messages[i]['sender'], messages[i]['content'])
        
    def prepare_a_new_chatbot(self):
        # Create chatbot
        self.chatbot_bindings = self.create_chatbot()
        # Chatbot conditionning
        self.condition_chatbot()
        return self.chatbot_bindings

    def id(self):
        return self.current_discussion.discussion_id

    def send_message(self, message, url):
        message_id = self.current_discussion.add_message(
            "user", "testing"
        )
    
        t = threading.Thread(target= self.generate_in_thread, args=(self.id(), self.db, self.config, url, message))
        print("starting thread")
        return str(t.start())

    @staticmethod
    def generate_in_thread(id, db, config, call_back_url, message):
        chat = ChatbotInstance.find_and_restore(id, db, config)

        messages = chat.current_discussion.get_messages()
        if not messages:
            messages = ['']

        chat.prompt_message = ""
        for i in range(min(len(messages), 4)):
            chat.prompt_message += "\n {}: {} \n".format(messages[i]['sender'], messages[i]['content'])

        chat.prompt_message += "user: "+message
        chat.current_message = "user: "+message

        reply = chat.generate_message()
        new_data = reply.split(message)[-1]
        print(new_data)
        print("=========================")
        real_reply = new_data.split("### Human")[0]
        print(real_reply)
        response_id = chat.current_discussion.add_message(
            "GPT4All", real_reply
        )
        data = {
            "message": real_reply.split("### Assistant:")[-1]
        }

        json_data = json.dumps(data)

        headers = {"Content-Type": "application/json"}
        response = requests.post(call_back_url, data=json_data, headers=headers)
        if response.status_code == 200:
            print("Message sent successfully!")
        else:
            print("Error occurred: ", response.text)

    def title(self):
        # TODO(Michael): figure out how to get the title out of the database...
        return ""

    def create_chatbot(self):
        return Model(
            ggml_model=f"./models/{self.config['model']}", 
            n_ctx=self.config['ctx_size'], 
            seed=self.config['seed'],
            )
    def condition_chatbot(self, conditionning_message = """
Instruction: Act as GPT4All. A kind and helpful AI bot built to help users solve problems.
GPT4All:Welcome! I'm here to assist you with anything you need. What can I do for you today?"""
                          ):
        if self.current_discussion is None:
            if self.db.does_last_discussion_have_messages():
                self.current_discussion = self.db.create_discussion()
            else:
                self.current_discussion = self.db.load_last_discussion()
        
        message_id = self.current_discussion.add_message(
            "conditionner", conditionning_message, DiscussionsDB.MSG_TYPE_CONDITIONNING,0
        )
    def __init__(self, db, config:dict) -> None:
        # workaround for non interactive mode
        self.prompt_message = ""
        self.config = config
        self.db = db
        self.current_discussion = None

    # NOTE(Michael): This find will restore the chat and consume resources, it's NOT grabing ids
    @staticmethod
    def find_and_restore(id, db, config):
        chat = ChatbotInstance(db, config)
        chat.restore_discussion(id)
        return chat

    # NOTE(Michael): This find will not restore the chat, it's for grabing ids to rename or delete
    @staticmethod
    def find(id, db, config):
        chat = ChatbotInstance(db, config)
        chat.current_discussion = Discussion(id, db)
        return chat


class Gpt4allGrpc(chat_pb2_grpc.ChatServiceServicer):
        

    def __init__(self, config:dict) -> None:
        super 
        self.config = config
        self.db_path = config["db_path"]
        self.db = DiscussionsDB(self.db_path)
        # If the database is empty, populate it with tables
        self.db.populate()

        

    def get_all_discussions(self):
        chats =[]
        for sub_dict in self.db.get_discussions():
            chat = chat_pb2.Chat()
            json_format.ParseDict(sub_dict, chat)
            chats.append(chat)
        return chats

    def SendChatMessage(self, request, context):
        chat = ChatbotInstance.find(request.chat_id, self.db, self.config)
        reply = chat.send_message(request.message, request.callback_url)
        return chat_pb2.SendChatMessageResponse(message=reply)

    def GetAllChats(self, request, context):
        discussions = self.get_all_discussions()
        return chat_pb2.GetAllChatsResponse(chats=discussions)

    def GetChat(self, request, context):
        chat = ChatbotInstance.find(request.id, self.db, self.config)
        print(chat.current_discussion.get_messages())
        # for message in chat.current_discussion.get_messages:
        #     print(message)
        return chat_pb2.GetChatResponse(chats=discussions)

    def DeleteChat(self, request, context):
        chat = ChatbotInstance.find(request.id, self.db, self.config)
        chat.current_discussion.delete_discussion()
        return chat_pb2.DeleteChatResponse()

    def CreateChat(self, request, context):
        new_chat = ChatbotInstance(self.db, self.config)
        new_chat.prepare_a_new_chatbot()
        return chat_pb2.CreateChatResponse(chat=chat_pb2.Chat(id=new_chat.id(), title=new_chat.title()))
        

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Start the chatbot Flask app.")
    parser.add_argument(
        "-s", "--seed", type=int, default=None, help="Force using a specific model."
    )

    parser.add_argument(
        "-m", "--model", type=str, default=None, help="Force using a specific model."
    )
    parser.add_argument(
        "--temp", type=float, default=None, help="Temperature parameter for the model."
    )
    parser.add_argument(
        "--n_predict",
        type=int,
        default=None,
        help="Number of tokens to predict at each step.",
    )
    parser.add_argument(
        "--top_k", type=int, default=None, help="Value for the top-k sampling."
    )
    parser.add_argument(
        "--top_p", type=float, default=None, help="Value for the top-p sampling."
    )
    parser.add_argument(
        "--repeat_penalty", type=float, default=None, help="Penalty for repeated tokens."
    )
    parser.add_argument(
        "--repeat_last_n",
        type=int,
        default=None,
        help="Number of previous tokens to consider for the repeat penalty.",
    )
    parser.add_argument(
        "--ctx_size",
        type=int,
        default=None,#2048,
        help="Size of the context window for the model.",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="launch Flask server in debug mode",
    )
    parser.add_argument(
        "--host", type=str, default="localhost", help="the hostname to listen on"
    )
    parser.add_argument("--port", type=int, default=None, help="the port to listen on")
    parser.add_argument(
        "--db_path", type=str, default=None, help="Database path"
    )
    parser.set_defaults(debug=False)
    args = parser.parse_args()
    config_file_path = "configs/default.yaml"
    config = load_config(config_file_path)

    # Override values in config with command-line arguments
    for arg_name, arg_value in vars(args).items():
        if arg_value is not None:
            config[arg_name] = arg_value
    

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        Gpt4allGrpc(config), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Ready...")
    server.wait_for_termination()