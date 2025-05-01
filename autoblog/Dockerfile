# Use a lightweight base image like Alpine Linux
FROM alpine:latest

# Argument to specify the PocketBase version. Check GitHub releases for the latest stable version.
ARG PB_VERSION=0.22.14

# Install necessary packages: unzip for extracting PocketBase, ca-certificates for HTTPS downloads
RUN apk add --no-cache unzip ca-certificates

# Download the specified PocketBase version for Linux AMD64 architecture
# Note: This assumes an AMD64 build environment. The previous version handled ARM64 too.
# If deploying on ARM64, this ADD command will need adjustment or revert to the previous multi-stage build.
ADD https://github.com/pocketbase/pocketbase/releases/download/v${PB_VERSION}/pocketbase_${PB_VERSION}_linux_amd64.zip /tmp/pb.zip

# Unzip PocketBase into the /pb/ directory
RUN unzip /tmp/pb.zip -d /pb/

# Clean up the downloaded zip file
RUN rm /tmp/pb.zip

# Expose the port that PocketBase will listen on inside the container.
# Render typically sets a PORT environment variable (e.g., 8080 or 10000)
# and expects the application to listen on that port.
EXPOSE 8080

# Define the command to run when the container starts.
# This runs the PocketBase executable in 'serve' mode.
# It listens on all network interfaces (0.0.0.0) inside the container
# on the port specified (matching the EXPOSE line).
# The --dir flag is important for Render's persistent disk mounting.
CMD ["/pb/pocketbase", "serve", "--http=0.0.0.0:8080", "--dir=/pb/pb_data"]

# Note: PocketBase data will be stored in /pb/pb_data inside the container by the CMD flag.
# This path needs to be mounted to a persistent disk in the Render configuration (render.yaml).
# Ensure the mountPath in render.yaml matches /pb/pb_data.