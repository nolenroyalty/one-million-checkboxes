#!/bin/bash
cat hosts | xargs -n 1 -P 10 -I'{}' ssh root@{} "journalctl -f" 
