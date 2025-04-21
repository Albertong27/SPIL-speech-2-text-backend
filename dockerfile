FROM node:18

# Install Vim
RUN apt-get update && apt-get install -y vim

# Set the working directory
WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the entire project
COPY . .

RUN mkdir -p dist/public && cp -r src/public/* dist/public

# Expose the application port
EXPOSE 3000

# Compile TypeScript
RUN npm run build

# Start the server
CMD ["node", "dist/index.js"]