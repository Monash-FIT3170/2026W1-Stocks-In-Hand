# Changes the default githooks path for just this repository. For more about githooks see: https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks
# By changing the githooks path, we can version control our githooks along with the rest of our code
git config core.hooksPath .githooks

# A docker image used in the backend Dockerfile. It is indirectly called by the docker-compose.yml
# file and causes issues, so it is easier to pull directly first
docker pull --quiet alpine/git:v2.52.0

########################################
##### CRLF Correction and flushing #####
########################################

# This prevents windows from converting files to a CRLF line ending (CRLF is unreadable by the docker images)
git config core.autocrlf false

### Now that the config is updated, need to reset all files so that they have LF line ending instead of CRLF
# Confirm that user understand what is about to be run prior to running it
confirm=" "

message="
---------------------------------------------------------------------------------------------------------------
WARNING: Please commit all changes before continuing with this script! This script runs the following commands:
git rm --cached -r .
git reset --hard

By continuing you confirm that ANY UNCOMMITTED CHANGES WILL BE LOST. Do you want to continue? (y/n):
"

# Get and validate user input
while [[ "$confirm" != "y" && "$confirm" != "n" ]]; do
    read -p "$message" confirm
done

# If user wants to cancel, exit the program
if [[ $confirm == "n" ]];
then
    echo -e "\nPlease commit changes and then re-run this script to finish setup"
    exit 0
fi

# Removes all files to get rid of their current version
git rm --cached -r .

# Resets all files to last commit
git reset --hard