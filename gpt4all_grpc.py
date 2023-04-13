import grpc
from concurrent import futures
import protos.chat_pb2 as chat_pb2
import protos.chat_pb2_grpc as chat_pb2_grpc

class Gpt4allGrpc(chat_pb2_grpc.ChatServiceServicer):
    def SendChatMessage(self, request, context):
        message = 'Hello {}!'.format(request.chat_id)
        return chat_pb2_grpc.ChatService.SendChatMessageResponse(message=message)
        

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        Gpt4allGrpc(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()