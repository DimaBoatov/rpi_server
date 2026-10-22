# Raspberry Pi Web Server

A starting point for hosting a website on a Raspberry Pi using Raspberry Pi OS and Nginx. This repository currently contains setup documentation; add your website files as the project develops.

## Requirements

- Raspberry Pi with Raspberry Pi OS installed
- microSD card and suitable power supply
- Ethernet or Wi-Fi connection
- Terminal access, either locally or over SSH
- A user account with `sudo` privileges

## Set up the server

Run these commands on your Raspberry Pi.

### 1. Update the system

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Install Nginx

```bash
sudo apt install nginx -y
sudo systemctl enable --now nginx
```

Check that the web server is running:

```bash
systemctl status nginx
```

### 3. Open the website

Find the Raspberry Pi's local IP address:

```bash
hostname -I
```

On a device connected to the same network, open `http://<PI_IP_ADDRESS>` in a browser. Replace `<PI_IP_ADDRESS>` with the Pi's local address, for example `192.168.1.50`. You should see the Nginx welcome page.

## Publish website files

Nginx's default website directory on Raspberry Pi OS is `/var/www/html`.

To create a simple home page, run:

```bash
printf '%s\n' '<!doctype html>' '<html lang="en">' '<meta charset="utf-8">' '<title>Raspberry Pi Web Server</title>' '<h1>Hello from Raspberry Pi!</h1>' '</html>' | sudo tee /var/www/html/index.html > /dev/null
```

Refresh the browser to see the new page. This command replaces an existing `index.html`, so back it up first if needed.

For a larger static website, copy its HTML, CSS, JavaScript, and image files into `/var/www/html`. Keep `index.html` at the root of that directory. Static file changes do not require restarting Nginx.

## Manage the server

| Task | Command |
| --- | --- |
| Check status | `sudo systemctl status nginx` |
| Start | `sudo systemctl start nginx` |
| Stop | `sudo systemctl stop nginx` |
| Restart | `sudo systemctl restart nginx` |
| Validate configuration | `sudo nginx -t` |
| Reload configuration | `sudo systemctl reload nginx` |
| View access logs | `sudo tail -f /var/log/nginx/access.log` |
| View error logs | `sudo tail -f /var/log/nginx/error.log` |

After editing Nginx configuration, validate it before reloading:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Network access and security

These instructions set up an HTTP server for your local network. For a stable local address, configure a DHCP reservation for the Raspberry Pi in your router.

Before making the server accessible from the internet:

- Install system updates regularly.
- Use SSH keys and protect administrative access.
- Configure a firewall to allow only required services, preserving SSH access if you manage the Pi remotely.
- Configure a domain and HTTPS with a valid TLS certificate.
- Review router port forwarding and expose only the services you intend to publish.
- Keep credentials, private keys, and other sensitive files outside the website directory and this repository.

## Troubleshooting

- **Website does not load:** Confirm that both devices are on the same network, verify the Pi's IP address, and check the Nginx service status.
- **Welcome page still appears:** Confirm that your `index.html` is in `/var/www/html` and refresh the browser cache.
- **403 Forbidden:** Check file permissions and ensure the website directory contains an index file readable by Nginx.
- **Configuration reload fails:** Run `sudo nginx -t` and inspect the error log.

## Possible next steps

- Add website source files to this repository.
- Document deployment steps specific to your application.
- Add HTTPS, backups, and monitoring.
- Add a reverse proxy configuration if the project later includes an application server.
