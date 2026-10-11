from config import client

# Generate response
response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="my name is rohit kumar agrawal say hello to me and tell me abot ai " 
)

print(response.text)


# for model in client.models.list():
#     print(model.name)