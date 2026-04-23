# Changes the default githooks path for just this repository. For more about githooks see: https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks
# By changing the githooks path, we can version control our githooks along with the rest of our code
git config core.hooksPath .githooks

# This prevents windows from converting files to a CRLF line ending, which makes them unreadable by the docker images
git config core.autocrlf false

# A docker image used in the backend Dockerfile. It is indirectly called by the docker-compose.yml
# file and causes issues, so it is easier to pull directly first
docker pull alpine/git:v2.52.0