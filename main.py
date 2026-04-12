from frontend.main import app


if __name__ == "__main__":
    import uvicorn

    #同一个局域网下的设备访问时可以使用这个，访问网站为ip地址:8000，ip地址可以在cmd中输入ipconfig查看WLAN适配器的IPv4地址
    #uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False) 


    #本地访问时使用这个，访问网站为http://127.0.0.1:8000/
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)