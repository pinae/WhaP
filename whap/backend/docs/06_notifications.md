# Notifications

Whale Pond tells you when something is about to happen to your containers or your data:

- **Server maintenance**: a compute server running one of your containers will be restarted or taken offline. The message says when, and what happens to your containers: usually they are stopped, and you start them again afterwards.
- **Expiring local containers**: 7 days and 1 day before the directory of a `local_` project is deleted from the compute server's SSD, with a link to prolong it by four weeks.
- **Image updates**: a newer version of an image you use is available.
- **Dataset updates**: a dataset one of your containers mounts has new data.

Pina may also write to everyone, or to the members of a Whale Pond group you are in. Those messages reach you whatever topics you switched off.

## Where they reach you

Open the settings with the gear icon next to Logout.

**Email** is on from the start and goes to the address of your university account. Local accounts have the address the admin set; if there is none, the settings page says so.

**Matrix** is optional. Whale Pond fills in your university Matrix ID (your RUB-ID before the colon); change it if you use another account. Click *Connect*: Whale Pond's bot invites you to a chat and sends a six-digit code. Accept the invitation in your Matrix app (Element, for example) and enter the code in the settings within 15 minutes. From then on, every notification also arrives in that chat. *Change* switches to another Matrix account, *Disconnect* stops the messages and the bot leaves the chat.

*Send me a test notification* writes to every place that is switched on, so you can check that it arrives.

## What they are about

The four switches under *What to tell you about* decide which topics you hear about. Each topic goes to every place that is switched on.

Server maintenance and expiring local containers are marked *Protects your data*. If you switch both off, or switch off every place Whale Pond could reach you, the settings ask you to confirm that your containers may be stopped, and local project directories deleted, without warning. After that a yellow banner reminds you on the settings page and the User Panel until you turn notifications back on.

## Inside Whale Pond

Whatever your settings, the User Panel shows above its tabs:

- maintenance that affects your containers, until it is over;
- your `local_` projects that expire within a week, with a *Prolong 4 weeks* button.

The link in an expiry email opens the same question: *Prolong "project" by four weeks?*

*Why did I get a message?* The last lines of every notification say why: which server, image, dataset or group it was about. They also link to your settings.
