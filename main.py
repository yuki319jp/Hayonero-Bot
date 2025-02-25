import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time
import pytz
import sqlite3
import json
import hashlib
import os
from base64 import b64encode, b64decode

#tokenを指定する
TOKEN = 'BOT_TOKEN_HERE'


# Intentsの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

class Encryptor:
    def __init__(self):
        # 環境変数から暗号化キーを取得、なければ新規作成
        self.salt = os.getenv('ENCRYPTION_SALT')
        if not self.salt:
            self.salt = os.urandom(16)
            print('警告: 新しいソルトが生成されました。このソルトを安全に保管してください。')
            print(f'ENCRYPTION_SALT={b64encode(self.salt).decode()}')
        else:
            self.salt = b64decode(self.salt)

    def encrypt(self, data: str) -> str:
        if not data:
            return ''
        # saltと組み合わせてハッシュ化
        hash_obj = hashlib.sha256(self.salt)
        hash_obj.update(data.encode())
        return b64encode(hash_obj.digest()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        # SHA256はハッシュ関数なので復号はできません
        # 代わりに暗号化済みデータをそのまま返します
        return encrypted_data

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect('bot_settings.db')
        self.encryptor = Encryptor()
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        # ハッシュ化されたデータ用のテーブル
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id TEXT,
            message TEXT,
            times TEXT
        )
        ''')
        # 平文データ用のテーブル
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings_plain (
            guild_id INTEGER PRIMARY KEY,
            channel_id TEXT,
            message TEXT,
            times TEXT
        )
        ''')
        self.conn.commit()

    def get_guild_settings(self, guild_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM guild_settings_plain WHERE guild_id = ?', (guild_id,))
        row = cursor.fetchone()
        if row:
            try:
                return {
                    'channel_id': int(row[1]) if row[1] else None,
                    'message': row[2],
                    'times': json.loads(row[3]) if row[3] else []
                }
            except Exception as e:
                print(f"データ取得エラー: {e}")
                return {'times': [], 'channel_id': None, 'message': None}
        return {'times': [], 'channel_id': None, 'message': None}

    def save_guild_settings(self, guild_id, settings):
        cursor = self.conn.cursor()
        try:
            # データのハッシュ化
            channel_id = self.encryptor.encrypt(str(settings['channel_id'])) if settings.get('channel_id') else None
            message = self.encryptor.encrypt(settings['message']) if settings.get('message') else None
            times = self.encryptor.encrypt(json.dumps(settings['times']))

            cursor.execute('''
            INSERT OR REPLACE INTO guild_settings (guild_id, channel_id, message, times)
            VALUES (?, ?, ?, ?)
            ''', (guild_id, channel_id, message, times))
            
            # 平文のデータも別テーブルに保存（復号用）
            cursor.execute('''
            INSERT OR REPLACE INTO guild_settings_plain (
                guild_id, channel_id, message, times
            ) VALUES (?, ?, ?, ?)
            ''', (
                guild_id,
                str(settings['channel_id']) if settings.get('channel_id') else None,
                settings.get('message'),
                json.dumps(settings['times'])
            ))
            self.conn.commit()
        except Exception as e:
            print(f"データ保存エラー: {e}")

class HayoneroBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.initial_sync_done = False
        self.db = DatabaseManager()

    async def setup_hook(self):
        if not self.initial_sync_done:
            print('コマンドを同期中...')
            try:
                synced = await self.tree.sync()
                print(f'{len(synced)}個のコマンドを同期しました')
                self.initial_sync_done = True
            except Exception as e:
                print(f'コマンドの同期中にエラーが発生しました: {e}')

bot = HayoneroBot()

# 日本のタイムゾーンを設定
JST = pytz.timezone('Asia/Tokyo')

# 設定を保存する変数を修正
guild_settings = {}

@bot.event
async def on_ready():
    print(f'{bot.user} としてログインしました')
    print('------------------------')
    print('利用可能なコマンド:')
    for cmd in bot.tree.get_commands():
        print(f'/{cmd.name} - {cmd.description}')
    print('------------------------')
    check_late_night.start()

@bot.tree.command(
    name="addtime",
    description="通知する時刻を追加します"
)
@app_commands.describe(
    hour="時間（0-23）",
    minute="分（0-59、省略可能）"
)
async def slash_add_notification_time(
    interaction: discord.Interaction, 
    hour: app_commands.Range[int, 0, 23],
    minute: app_commands.Range[int, 0, 59] = 0
):
    guild_id = interaction.guild_id
    settings = bot.db.get_guild_settings(guild_id)
    
    time_str = f"{hour:02d}:{minute:02d}"
    if time_str not in settings['times']:
        settings['times'].append(time_str)
        bot.db.save_guild_settings(guild_id, settings)
        await interaction.response.send_message(
            f'✅ 通知時刻 {time_str} を追加しました'
        )
    else:
        await interaction.response.send_message(
            f'⚠️ 通知時刻 {time_str} はすでに設定されています'
        )

@bot.tree.command(name="removetime", description="通知する時刻を削除します")
async def slash_remove_notification_time(
    interaction: discord.Interaction, 
    hour: app_commands.Range[int, 0, 23],
    minute: app_commands.Range[int, 0, 59] = 0
):
    guild_id = interaction.guild_id
    settings = bot.db.get_guild_settings(guild_id)
    
    time_str = f"{hour:02d}:{minute:02d}"
    if time_str in settings['times']:
        settings['times'].remove(time_str)
        bot.db.save_guild_settings(guild_id, settings)
        await interaction.response.send_message(
            f'✅ 通知時刻 {time_str} を削除しました'
        )
    else:
        await interaction.response.send_message(
            f'⚠️ 通知時刻 {time_str} は設定されていません'
        )

@bot.tree.command(
    name="setchannel",
    description="通知を送信するチャンネルを設定します"
)
@app_commands.describe(
    channel="通知を送信するテキストチャンネル"
)
async def slash_set_notification_channel(
    interaction: discord.Interaction, 
    channel: discord.TextChannel
):
    guild_id = interaction.guild_id
    settings = bot.db.get_guild_settings(guild_id)
    
    try:
        # チャンネルの権限チェック
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message(
                f'⚠️ {channel.mention} への送信権限がありません。',
                ephemeral=True
            )
            return

        settings['channel_id'] = channel.id
        bot.db.save_guild_settings(guild_id, settings)
        await interaction.response.send_message(
            f'✅ 通知チャンネルを {channel.mention} に設定しました'
        )
    except Exception as e:
        print(f"チャンネル設定エラー: {e}")
        await interaction.response.send_message(
            "チャンネルの設定中にエラーが発生しました",
            ephemeral=True
        )

@bot.tree.command(name="setmessage", description="通知メッセージを設定します")
async def slash_set_message(
    interaction: discord.Interaction,
    message: str
):
    guild_id = interaction.guild_id
    settings = bot.db.get_guild_settings(guild_id)
    
    settings['message'] = message
    bot.db.save_guild_settings(guild_id, settings)
    await interaction.response.send_message(f'通知メッセージを設定しました:\n{message}')

@bot.tree.command(name="listtimes", description="設定されている通知時刻一覧を表示します")
async def slash_list_times(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    settings = bot.db.get_guild_settings(guild_id)
    
    if not settings['times']:
        await interaction.response.send_message('通知時刻が設定されていません')
        return
    
    times = sorted([datetime.strptime(t, '%H:%M').time() for t in settings['times']])
    times_str = '\n'.join([f'• {t.strftime("%H:%M")}' for t in times])
    message = settings['message'] or '⚠️ もう深夜です！そろそろ休みましょう！'
    
    embed = discord.Embed(
        title="通知設定一覧",
        color=discord.Color.blue()
    )
    embed.add_field(name="通知時刻", value=times_str, inline=False)
    embed.add_field(name="通知メッセージ", value=message, inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="botinfo", description="ボットの使い方を表示します")
async def slash_show_info(interaction: discord.Interaction):
    help_embed = discord.Embed(
        title="はよねろボットの使い方",
        description="各コマンドの使い方は以下の通りです：",
        color=discord.Color.blue()
    )
    help_embed.add_field(
        name="/addtime [時] [分]",
        value="通知する時刻を追加します\n例: `/addtime 23 30` (23時30分に通知)",
        inline=False
    )
    help_embed.add_field(
        name="/removetime [時] [分]",
        value="設定された通知時刻を削除します\n例: `/removetime 23 30` (23時30分の通知を削除)",
        inline=False
    )
    help_embed.add_field(
        name="/listtimes",
        value="現在設定されている通知時刻の一覧を表示します",
        inline=False
    )
    help_embed.add_field(
        name="/setchannel [チャンネル]",
        value="通知を送信するチャンネルを設定します\n例: `/setchannel #general`",
        inline=False
    )
    help_embed.add_field(
        name="/setmessage [メッセージ]",
        value="通知時に送信するメッセージを設定します\n例: `/setmessage 寝る時間です！おやすみなさい！`",
        inline=False
    )
    help_embed.add_field(
        name="Bot System Info",
        value="Ver.1.0.0 Beta / python 3.12.0 / discord.py 2.0.0",
        inline=False
    )
    await interaction.response.send_message(embed=help_embed)

@tasks.loop(minutes=1)
async def check_late_night():
    try:
        now = datetime.now(JST)
        current_time = now.strftime('%H:%M')
        
        for guild in bot.guilds:
            try:
                settings = bot.db.get_guild_settings(guild.id)
                if not settings or not settings['times']:
                    continue

                if current_time in settings['times']:
                    online_members = [
                        member for member in guild.members 
                        if str(member.status) != 'offline' 
                        and not member.bot
                    ]
                    
                    if online_members and settings.get('channel_id'):
                        channel = guild.get_channel(settings['channel_id'])
                        if channel and channel.permissions_for(guild.me).send_messages:
                            message = settings.get('message') or '⚠️ もう深夜です！そろそろ休みましょう！'
                            online_members_mention = ' '.join([member.mention for member in online_members])
                            await channel.send(f"{message}\n{online_members_mention}")

            except Exception as e:
                print(f"Guild {guild.id} の通知処理でエラー: {str(e)}")
    except Exception as e:
        print(f"check_late_night でエラー: {str(e)}")

# エラーハンドリング
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('❌ 必要な引数が不足しています。`!commands` で使い方を確認してください。')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('❌ 引数の形式が正しくありません。`!commands` で使い方を確認してください。')
    else:
        print(f'エラーが発生しました: {error}')

# エラーハンドリングを改善
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f'コマンドを使用するには {error.retry_after:.2f} 秒待つ必要があります',
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            'このコマンドを使用する権限がありません',
            ephemeral=True
        )
    else:
        print(f'コマンドエラー: {error}')
        await interaction.response.send_message(
            'コマンドの実行中にエラーが発生しました',
            ephemeral=True
        )

# Discordボットのトークンを入れてください
bot.run(TOKEN)
