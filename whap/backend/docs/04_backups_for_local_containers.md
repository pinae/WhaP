# Backups for local_ containers

Since `synced_` containers always sync the whole home directory to the storageserver you do not need to think about 
backups. The whole `$HOME` is transferred to the storageserver which uses ZFS in a RAID-6-Style configuration with daily 
snapshots which offers excellent protection of the data.

For `local_` containers the home directory lives on the SSD of the compute server which needs to be cleaned up 
regularly. So the `~/ttl.txt` saves the date until the data is kept. If you are not careful you might forget to save 
precious data and it gets wiped automatically. However since `~/synced/` is always present you have an easy option to
save precious data on the storageserver with the same high level of data protection as in the `synced_` containers. The 
easiest way to use this is by simple `cp` or even using the directory in the production code.

 * You can simply remind yourself to copy data worth keeping with `cp` or `rsync` into `~/synced/`. This especially 
   makes sense after finishing a run of experiments and the only data worth keeping are the results. Simply copy them to
   `~/synced/` and delete the container. You may also enter the same day in `ttl.txt` so the space on the SSD is freed 
   up as fast as possible. Freeing up space like this is being kind to your fellow researchers who might need the space 
   on the SSD.
 * You can use `~/synced/` directly in the code of your experiments. Often times the results are not huge files and 
   saving them with ~115 MB/s over the NFS connection does not introduce a big bottleneck for the runtime of your 
   computational experiments. Using it this way has the benefit that the results are safely stored on the storageserver
   immediately and you do not need to remember to put them there.

## Automatic Backups with Restic

If none of the above is suitable for your usecase and you want to automate your workflow you can install 
[Restic](https://restic.net/#quickstart) as a backup tool:

```shell
sudo apt install restic
```

Restic uses a ["repository" where it saves the backups](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html#local). 
Use `~/synced/` there (or a subfolder):

```shell
restic -r ~/synced/ init
```

Restic will ask for a password for encrypting the backups. You can use it empty. If you set one make sure to not forget
it. Restic is encrypting the data in a way you will not be able to break.

The command you need for running a backup is:
```shell
restic -r ~/synced/ --verbose backup . --skip-if-unchanged --exclude="~/synced/"
```

If you want to exclude more than the `synced/` folder you may want to 
[create a `excludes.txt`](https://restic.readthedocs.io/en/stable/040_backup.html#excluding-files) and add the option 
`--exclude-file=excludes.txt`.

Instead of specifying the repository with `-r` you can set the 
[environment variable `RESTIC_REPOSITORY`](https://restic.readthedocs.io/en/stable/040_backup.html#environment-variables).

To automatically run the restic backup every hour with the `cron` daemon you need to add it to the crontab by running 
`crontab -e`. Add this line:   

```cron
0 * * * * /usr/bin/restic -r /home/yourusername/synced/ backup /home/yourusername --skip-if-unchanged --exclude="/home/yourusername/synced/" >> /home/yourusername/restic.log 2>&1
```

If you set a password for your backups repository you need to provide this to the command. `cron` does not have the
environment of your shell so the commands need to use full paths without `~` or variables like `$HOME´. The recommended 
way to store the password is in a password file you create like this:
```shell
echo "your_restic_password" > ~/.restic_password
chmod 600 ~/.restic_password
```

You pass this file to `restic` by setting the environment variable `RESTIC_PASSWORD_FILE` in front of your command in 
the crontab:

```cron
0 * * * * RESTIC_PASSWORD_FILE=/home/yourusername/.restic_password /usr/bin/restic -r /home/yourusername/synced/ backup /home/yourusername --skip-if-unchanged --exclude="/home/yourusername/synced/" >> /home/yourusername/restic.log 2>&1
```

### Automatically deleting unnecessary backups

It makes sense to [thin out the number of snapshots with time](https://restic.readthedocs.io/en/stable/060_forget.html#removing-snapshots-according-to-a-policy). 
The following command runs every dat at 2:30 am and keeps the last 7, one every day for the last 14 days and one each 
week for the last year:

```cron
30 2 * * * RESTIC_PASSWORD_FILE=/home/yourusername/.restic_password /usr/bin/restic -r /home/yourusername/synced/ forget --keep-last 7 --keep-daily 14 --keep-weekly 52 --prune >> /home/yourusername/restic.log 2>&1
```

Remove `RESTIC_PASSWORD_FILE=/home/yourusername/.restic_password` from the above command if you haven't set a password.

You can also regularly check the integrity of you backups at 3:30 am:

```cron
30 3 * * * RESTIC_PASSWORD_FILE=/home/yourusername/.restic_password /usr/bin/restic -r /home/yourusername/synced/ check >> /home/yourusername/restic.log 2>&1
```

### Using Restic bare metal

If you are using a compute server bare metal you may also want to use `restic` for your backups. In this case the
repository would be `/data/yourRUBid/projectname/` or a subfolder of that. Please make sure to also tidy up your
crontab after a project was finished because you might create unnecessary regular loads on the server otherwise.