Run the following command to build the docker for tensorcircuit at parent path:

```bash
sudo docker build . -f docker/Dockerfile -t tensorcircuit
```

One can also pull the [official image](https://hub.docker.com/repository/docker/tensorcircuit/tensorcircuit) from DockerHub as 

```bash
sudo docker pull tensorcircuit/tensorcircuit
```


Run the docker container by the following command:

```bash
sudo docker run -it --network host --gpus all tensorcircuit/tensorcircuit

# if one also wants mount local source code, also add args `-v "$(PWD)":/tmp`

# for old dockerfile with no runtime env setting
# sudo docker run -it --network host -e LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda-11.0/targets/x86_64-linux/lib -e PYTHONPATH=/app -v "$(pwd)":/app  --gpus all tensorcircuit
```

`export TF_CPP_MIN_LOG_LEVEL=3` maybe necessary since jax suprisingly frequently complain about ptxas version problem. And `export CUDA_VISIBLE_DEVICES=-1` if you want to test only on CPU.
