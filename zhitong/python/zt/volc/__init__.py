"""火山引擎运维（zt-volc）：``ve`` CLI 与 ssh 的封装，参数校验，危险操作需显式 ``--yes``。

原型是用户本机的 ``vec``（``ve --profile <profile>`` 封装）、``ssh-access-sync.sh``（把当前公网 IP 同步进
安全组白名单）与 ``pssh``（用 ``~/.ssh/config`` 的别名登录服务器）；这里不含它们的源码，只实现同样的功能。
凭据与主机别名的**名称**来自环境变量或配置文件路径（:mod:`zt.volc.config`），本包不含任何值。
"""
